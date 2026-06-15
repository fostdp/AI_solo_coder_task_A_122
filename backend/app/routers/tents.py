from fastapi import APIRouter, Query
from typing import Optional
from ..config import TENT_CONFIGS
from ..schemas import TentInfo

router = APIRouter(prefix="/api/tents", tags=["tents"])


@router.get("/", response_model=list[TentInfo])
def list_tents():
    return [TentInfo(**t) for t in TENT_CONFIGS]


@router.get("/{tent_id}", response_model=TentInfo)
def get_tent(tent_id: int):
    for t in TENT_CONFIGS:
        if t["id"] == tent_id:
            return TentInfo(**t)
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail="Tent not found")
