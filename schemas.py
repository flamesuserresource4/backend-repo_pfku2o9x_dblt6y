"""
Database Schemas for Loved Homes

Each Pydantic model represents a MongoDB collection. The collection name is the lowercase of the class name.
"""
from pydantic import BaseModel, Field
from typing import Optional

class Property(BaseModel):
    name: str = Field(..., description="Property display name")
    photo_url: Optional[str] = Field(None, description="URL of the uploaded cover photo")

class Checklistitem(BaseModel):
    property_id: str = Field(..., description="ID of the property this item belongs to")
    parent_id: Optional[str] = Field(None, description="Parent item ID for hierarchical structure")
    title: str = Field(..., description="Item title or folder name")
    is_folder: bool = Field(False, description="Whether this item is a folder containing sub-items")
