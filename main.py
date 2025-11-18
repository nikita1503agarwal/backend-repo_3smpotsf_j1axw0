import os
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from bson import ObjectId

from database import db, create_document, get_documents
from schemas import Food, Meal, MealItem, MealTotals

app = FastAPI(title="Nutrition API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Helpers ----------
class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if isinstance(v, ObjectId):
            return v
        try:
            return ObjectId(str(v))
        except Exception:
            raise ValueError("Invalid ObjectId")

def serialize_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    d = dict(doc)
    if "_id" in d:
        d["id"] = str(d.pop("_id"))
    # Convert nested ObjectIds if any
    for k, v in list(d.items()):
        if isinstance(v, ObjectId):
            d[k] = str(v)
    return d


# ---------- Root & Health ----------
@app.get("/")
def read_root():
    return {"message": "Nutrition API ready"}

@app.get("/api/hello")
def hello():
    return {"message": "Hello from the backend API!"}

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
            response["database_name"] = getattr(db, "name", None) or ""
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️ Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"
    return response


# ---------- Foods ----------
@app.post("/foods")
def create_food(food: Food):
    try:
        # Ensure unique by name (case-insensitive)
        existing = db["food"].find_one({"name": {"$regex": f"^{food.name}$", "$options": "i"}}) if db else None
        if existing:
            raise HTTPException(status_code=409, detail="Food with this name already exists")
        food_id = create_document("food", food)
        doc = db["food"].find_one({"_id": ObjectId(food_id)})
        return serialize_doc(doc)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/foods")
def list_foods(q: Optional[str] = None, limit: int = 100):
    try:
        filter_dict: Dict[str, Any] = {}
        if q:
            filter_dict = {"name": {"$regex": q, "$options": "i"}}
        docs = get_documents("food", filter_dict=filter_dict, limit=limit)
        return [serialize_doc(d) for d in docs]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------- Meal calculation & storage ----------
class CalcItem(BaseModel):
    food_id: str
    quantity_grams: float

class CalcRequest(BaseModel):
    items: List[CalcItem]

class CalcResponse(BaseModel):
    totals: MealTotals
    breakdown: List[dict]


def compute_totals(items: List[CalcItem]) -> Dict[str, Any]:
    if not items:
        return {
            "totals": {"calories": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0},
            "breakdown": []
        }
    ids = [ObjectId(i.food_id) for i in items]
    foods = list(db["food"].find({"_id": {"$in": ids}}))
    food_map = {str(f["_id"]): f for f in foods}

    totals = {"calories": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0}
    breakdown = []

    for i in items:
        f = food_map.get(i.food_id)
        if not f:
            raise HTTPException(status_code=404, detail=f"Food not found: {i.food_id}")
        factor = i.quantity_grams / 100.0
        cals = (f.get("calories_per_100g", 0) or 0) * factor
        prot = (f.get("protein_per_100g", 0) or 0) * factor
        carbs = (f.get("carbs_per_100g", 0) or 0) * factor
        fat = (f.get("fat_per_100g", 0) or 0) * factor
        totals["calories"] += cals
        totals["protein"] += prot
        totals["carbs"] += carbs
        totals["fat"] += fat
        breakdown.append({
            "food": f.get("name"),
            "food_id": i.food_id,
            "quantity_grams": i.quantity_grams,
            "calories": cals,
            "protein": prot,
            "carbs": carbs,
            "fat": fat,
        })

    for k in totals:
        totals[k] = round(totals[k], 2)
    for row in breakdown:
        for k in ["calories", "protein", "carbs", "fat"]:
            row[k] = round(row[k], 2)

    return {"totals": totals, "breakdown": breakdown}


@app.post("/meals/calc")
def calculate_meal(payload: CalcRequest):
    try:
        result = compute_totals(payload.items)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/meals")
def save_meal(meal: Meal):
    try:
        # Compute totals from provided items (authoritative)
        calc_items = [CalcItem(food_id=i.food_id, quantity_grams=i.quantity_grams) for i in meal.items]
        computed = compute_totals(calc_items)
        totals = MealTotals(**computed["totals"])  # type: ignore
        meal_data = meal.model_dump()
        meal_data["totals"] = totals.model_dump()
        meal_id = create_document("meal", meal_data)
        doc = db["meal"].find_one({"_id": ObjectId(meal_id)})
        return serialize_doc(doc)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/meals")
def list_meals(limit: int = 100):
    try:
        docs = get_documents("meal", limit=limit)
        # Attach human-readable items by joining with foods (optional minimal)
        food_ids = set()
        for m in docs:
            for it in m.get("items", []):
                if isinstance(it.get("food_id"), ObjectId):
                    it["food_id"] = str(it["food_id"])  # just in case
                food_ids.add(it.get("food_id"))
        food_map = {}
        if food_ids:
            foods = list(db["food"].find({"_id": {"$in": [ObjectId(fid) for fid in food_ids if fid]}}))
            food_map = {str(f["_id"]): f.get("name") for f in foods}
        result = []
        for d in docs:
            sd = serialize_doc(d)
            for it in sd.get("items", []):
                it["food_name"] = food_map.get(it.get("food_id"))
            result.append(sd)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
