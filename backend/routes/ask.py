from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional

from RAG_ENGINE.src.pipeline import answer_query
from backend.auth_utils import get_current_user, CurrentUser

router = APIRouter(prefix="/ask", tags=["Ask"])


class Message(BaseModel):
    role: str
    content: str

class AskRequest(BaseModel):
    question: str
    history: Optional[List[Message]] = []


# Chat was previously reachable by anyone, unauthenticated. Any logged-in
# role (student/faculty/admin) may use it, but a valid token is required.
@router.post("/")
def ask_question(payload: AskRequest, user: CurrentUser = Depends(get_current_user)):
    try:
        chat_history = [{"role": m.role, "content": m.content} for m in payload.history]
        result = answer_query(payload.question, chat_history=chat_history)
        return result
    except Exception as e:
        import traceback
        print("FULL ERROR:\n", traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))
