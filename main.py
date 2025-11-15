import os
from typing import List, Optional, Any, Dict
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from bson import ObjectId

from database import db, create_document, get_documents
from schemas import Property as PropertySchema, Checklistitem as ChecklistItemSchema

app = FastAPI(title="Loved Homes API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Helpers
class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if isinstance(v, ObjectId):
            return v
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid objectid")
        return ObjectId(v)


def serialize_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    if not doc:
        return doc
    doc = dict(doc)
    _id = doc.get("_id")
    if _id is not None:
        doc["id"] = str(_id)
        del doc["_id"]
    # Convert ObjectIds in fields
    for key in ["property_id", "parent_id"]:
        if key in doc and isinstance(doc[key], ObjectId):
            doc[key] = str(doc[key])
    return doc

# Root and health
@app.get("/")
def read_root():
    return {"message": "Loved Homes backend running"}

@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name
            response["connection_status"] = "Connected"
            collections = db.list_collection_names()
            response["collections"] = collections
            response["database"] = "✅ Connected & Working"
        else:
            response["database"] = "⚠️ Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"
    return response

# Image upload - returns a data URL to store as photo_url
@app.post("/api/upload")
async def upload_image(file: UploadFile = File(...)):
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    # Infer mime type from filename, fallback to image/jpeg
    mime = "image/jpeg"
    fname = (file.filename or "").lower()
    if fname.endswith(".png"):
        mime = "image/png"
    elif fname.endswith(".gif"):
        mime = "image/gif"
    import base64
    b64 = base64.b64encode(content).decode("utf-8")
    data_url = f"data:{mime};base64,{b64}"
    return {"url": data_url}

# Properties Endpoints
class PropertyCreate(BaseModel):
    name: str
    photo_url: Optional[str] = None

class PropertyUpdate(BaseModel):
    name: Optional[str] = None
    photo_url: Optional[str] = None

@app.get("/api/properties")
def list_properties():
    docs = get_documents("property")
    return [serialize_doc(d) for d in docs]

@app.post("/api/properties")
def create_property(payload: PropertyCreate):
    prop = PropertySchema(name=payload.name, photo_url=payload.photo_url)
    new_id = create_document("property", prop)
    doc = db["property"].find_one({"_id": ObjectId(new_id)})
    return serialize_doc(doc)

@app.patch("/api/properties/{property_id}")
def update_property(property_id: str, payload: PropertyUpdate):
    if not ObjectId.is_valid(property_id):
        raise HTTPException(status_code=400, detail="Invalid id")
    update: Dict[str, Any] = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not update:
        return {"updated": False}
    update["updated_at"] = __import__("datetime").datetime.utcnow()
    res = db["property"].update_one({"_id": ObjectId(property_id)}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    doc = db["property"].find_one({"_id": ObjectId(property_id)})
    return serialize_doc(doc)

@app.delete("/api/properties/{property_id}")
def delete_property(property_id: str):
    if not ObjectId.is_valid(property_id):
        raise HTTPException(status_code=400, detail="Invalid id")
    # delete property and its checklist items
    db["property"].delete_one({"_id": ObjectId(property_id)})
    db["checklistitem"].delete_many({"property_id": ObjectId(property_id)})
    return {"deleted": True}

# Checklist items Endpoints
class ItemCreate(BaseModel):
    title: str
    is_folder: bool = False
    parent_id: Optional[str] = None

@app.get("/api/properties/{property_id}/items")
def list_items(property_id: str, parent_id: Optional[str] = None):
    if not ObjectId.is_valid(property_id):
        raise HTTPException(status_code=400, detail="Invalid id")
    flt: Dict[str, Any] = {"property_id": ObjectId(property_id)}
    if parent_id:
        if not ObjectId.is_valid(parent_id):
            raise HTTPException(status_code=400, detail="Invalid parent id")
        flt["parent_id"] = ObjectId(parent_id)
    else:
        flt["parent_id"] = None
    docs = list(db["checklistitem"].find(flt).sort("title", 1))
    return [serialize_doc(d) for d in docs]

@app.post("/api/properties/{property_id}/items")
def create_item(property_id: str, payload: ItemCreate):
    if not ObjectId.is_valid(property_id):
        raise HTTPException(status_code=400, detail="Invalid id")
    parent_oid = None
    if payload.parent_id:
        if not ObjectId.is_valid(payload.parent_id):
            raise HTTPException(status_code=400, detail="Invalid parent id")
        parent_oid = ObjectId(payload.parent_id)
    item = ChecklistItemSchema(
        property_id=property_id,  # will convert below
        parent_id=payload.parent_id,
        title=payload.title,
        is_folder=payload.is_folder,
    ).model_dump()
    # fix ids
    item["property_id"] = ObjectId(property_id)
    item["parent_id"] = parent_oid
    from datetime import datetime, timezone
    item["created_at"] = datetime.now(timezone.utc)
    item["updated_at"] = datetime.now(timezone.utc)
    res = db["checklistitem"].insert_one(item)
    doc = db["checklistitem"].find_one({"_id": res.inserted_id})
    return serialize_doc(doc)

class ItemUpdate(BaseModel):
    title: Optional[str] = None
    is_folder: Optional[bool] = None

@app.patch("/api/items/{item_id}")
def update_item(item_id: str, payload: ItemUpdate):
    if not ObjectId.is_valid(item_id):
        raise HTTPException(status_code=400, detail="Invalid id")
    update: Dict[str, Any] = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not update:
        return {"updated": False}
    from datetime import datetime
    update["updated_at"] = datetime.utcnow()
    res = db["checklistitem"].update_one({"_id": ObjectId(item_id)}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    doc = db["checklistitem"].find_one({"_id": ObjectId(item_id)})
    return serialize_doc(doc)

@app.delete("/api/items/{item_id}")
def delete_item(item_id: str):
    if not ObjectId.is_valid(item_id):
        raise HTTPException(status_code=400, detail="Invalid id")
    # recursively delete children
    def delete_children(parent_oid: ObjectId):
        children = list(db["checklistitem"].find({"parent_id": parent_oid}))
        for ch in children:
            delete_children(ch["_id"])
            db["checklistitem"].delete_one({"_id": ch["_id"]})
    oid = ObjectId(item_id)
    delete_children(oid)
    db["checklistitem"].delete_one({"_id": oid})
    return {"deleted": True}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
