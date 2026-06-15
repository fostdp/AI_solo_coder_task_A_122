from fastapi import APIRouter, Query
from typing import List
from ..config import TENT_CONFIGS
from ..schemas import DrugRisk, PriorityRecommendation
from ..services.prediction import get_prediction_service

router = APIRouter(prefix="/api/drugs", tags=["drugs"])


@router.get("/risks/{tent_id}", response_model=List[DrugRisk])
def get_drug_risks(tent_id: int):
    tent = next((t for t in TENT_CONFIGS if t["id"] == tent_id), None)
    if not tent:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Tent not found")

    svc = get_prediction_service()
    risks = svc.assess_drug_risks(tent_id, tent["drugs"])

    svc.store_risk_assessments(risks)

    return [DrugRisk(**r) for r in risks]


@router.get("/priorities/{tent_id}", response_model=List[PriorityRecommendation])
def get_priorities(tent_id: int):
    tent = next((t for t in TENT_CONFIGS if t["id"] == tent_id), None)
    if not tent:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Tent not found")

    svc = get_prediction_service()
    recommendations = svc.get_priority_recommendations(tent_id, tent["drugs"])
    return [PriorityRecommendation(**r) for r in recommendations]


@router.get("/heatmap/{tent_id}")
def get_heatmap(tent_id: int):
    svc = get_prediction_service()
    return svc.get_heatmap_data(tent_id)


@router.get("/all-risks")
def get_all_risks():
    svc = get_prediction_service()
    all_risks = []
    for tent in TENT_CONFIGS:
        risks = svc.assess_drug_risks(tent["id"], tent["drugs"])
        svc.store_risk_assessments(risks)
        all_risks.extend(risks)
    return all_risks
