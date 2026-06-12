import logging

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Any, List, Optional

from entity_manager import (
    connect_autocad,
    connect_instruments,
    count_entities,
    delete_entity,
    get_available_symbols,
    get_drawing_details,
    get_entities,
    get_entity,
    get_status,
    insert_symbol,
    move_entity,
    refresh_entities,
    rotate_entity,
)
from schemas import (
    ConnectRequest,
    DeleteRequest,
    DrawingDetails,
    EntityMetadata,
    MoveRequest,
    RotateRequest,
    SymbolInsertRequest,
)
from agent_engine import AIAgent

logger = logging.getLogger(__name__)

app = FastAPI(title="AutoCAD CAD Control Platform")
app.mount("/static", StaticFiles(directory="static"), name="static")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class AgentChatRequest(BaseModel):
    message: str

class AgentChatResponse(BaseModel):
    success: bool
    response: str
    thought: Optional[str] = None
    steps: Optional[List[Any]] = []
    execution_results: Optional[List[Any]] = []
    summary: Optional[str] = None
    actions: Optional[List[Any]] = []
    tool_results: Optional[List[Any]] = []
    context: Optional[str] = None

    class Config:
        extra = "allow"

ai_agent = AIAgent()

@app.post("/agent/chat", response_model=AgentChatResponse)
def agent_chat(request: AgentChatRequest):
    logger.info("[API] Received /agent/chat request: %s", request.message)
    try:
        result = ai_agent.process_message(request.message)
        logger.info(
            "[API] Returning /agent/chat response: success=%s thought=%s",
            result.get("success"),
            result.get("thought"),
        )
        return result
    except Exception as exc:
        logger.error("[API] /agent/chat error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

@app.get("/", response_class=FileResponse)
def index():
    return FileResponse("static/index.html")

@app.get("/status")
def status():
    return get_status()

@app.get("/symbols/available", response_model=list[str])
def available_symbols():
    return get_available_symbols()

@app.post("/connect")
def connect():
    try:
        result = connect_autocad()
        if not result:
            raise HTTPException(status_code=500, detail="AutoCAD connection failed")
        return {
            "success": True,
            "result": result,
            "status": get_status(),
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("CONNECT ERROR: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=str(exc)
        )

@app.get("/entities", response_model=list[EntityMetadata])
def entities():
    return get_entities()

@app.get("/refresh", response_model=list[EntityMetadata])
def refresh_entities_endpoint():
    return refresh_entities()

@app.get("/entities/{handle}", response_model=EntityMetadata)
def entity(handle: str):
    try:
        return get_entity(handle)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))

@app.post("/symbols", response_model=EntityMetadata)
def add_symbol(request: SymbolInsertRequest):
    try:
        return insert_symbol(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@app.post("/entities/delete")
def delete_symbol(request: DeleteRequest):
    try:
        return delete_entity(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@app.post("/entities/move", response_model=EntityMetadata)
def move_symbol(request: MoveRequest):
    try:
        return move_entity(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@app.post("/entities/rotate", response_model=EntityMetadata)
def rotate_symbol_endpoint(request: RotateRequest):
    try:
        return rotate_entity(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@app.post("/pipes/connect")
def connect_pipe(request: ConnectRequest):
    try:
        return connect_instruments(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@app.get("/count")
def count():
    return {"count": count_entities()}

@app.get("/drawing/details", response_model=DrawingDetails)
def drawing_details():
    return get_drawing_details()
