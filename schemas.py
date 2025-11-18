"""
Database Schemas for Nutrition App

Each Pydantic model represents a collection in your database.
Collection name = lowercase of the class name.

- Food -> "food"
- Meal -> "meal"
"""

from pydantic import BaseModel, Field
from typing import List, Optional

class Food(BaseModel):
    """
    Food items with macros per 100g to standardize calculations
    Collection: "food"
    """
    name: str = Field(..., description="Food name")
    calories_per_100g: float = Field(..., ge=0, description="Calories per 100g")
    protein_per_100g: float = Field(..., ge=0, description="Protein (g) per 100g")
    carbs_per_100g: float = Field(..., ge=0, description="Carbs (g) per 100g")
    fat_per_100g: float = Field(0, ge=0, description="Fat (g) per 100g")

class MealItem(BaseModel):
    """An item in a meal referencing a food and its quantity in grams"""
    food_id: str = Field(..., description="ID of the food document")
    quantity_grams: float = Field(..., gt=0, description="Quantity in grams")

class MealTotals(BaseModel):
    calories: float
    protein: float
    carbs: float
    fat: float

class Meal(BaseModel):
    """
    Saved meals with items and computed totals
    Collection: "meal"
    """
    name: str = Field(..., description="Meal name")
    items: List[MealItem] = Field(default_factory=list)
    totals: Optional[MealTotals] = None
