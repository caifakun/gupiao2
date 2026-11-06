from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..core.security import require_csrf
from ..db.models import User
from ..db.session import get_database
from ..services import workspace
from .dependencies import require_user
from .schemas import WorkspaceUpdate

router = APIRouter(prefix="/api/workspace", tags=["workspace"])


@router.get("")
def read_workspace(user: User = Depends(require_user), database: Session = Depends(get_database)):
    return workspace.load_workspace(database, user.id)


@router.put("", dependencies=[Depends(require_csrf)])
def write_workspace(payload: WorkspaceUpdate, user: User = Depends(require_user), database: Session = Depends(get_database)):
    return workspace.save_workspace(database, user.id, payload)
