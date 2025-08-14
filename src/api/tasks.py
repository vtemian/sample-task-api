from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field, ConfigDict

from ..models.task import Task
from ..models.user import User
from ..core.database import get_db
from ..core.auth import get_current_user

router = APIRouter(prefix="/tasks", tags=["tasks"])


# Pydantic Models
class TaskCreate(BaseModel):
    """Schema for creating a new task"""
    title: str = Field(..., min_length=1, max_length=200, description="Task title")
    description: Optional[str] = Field(None, max_length=1000, description="Task description")
    completed: bool = Field(default=False, description="Task completion status")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "title": "Complete project documentation",
                "description": "Write comprehensive documentation for the API",
                "completed": False
            }
        }
    )


class TaskUpdate(BaseModel):
    """Schema for updating an existing task"""
    title: Optional[str] = Field(None, min_length=1, max_length=200, description="Task title")
    description: Optional[str] = Field(None, max_length=1000, description="Task description")
    completed: Optional[bool] = Field(None, description="Task completion status")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "title": "Updated task title",
                "description": "Updated task description",
                "completed": True
            }
        }
    )


class TaskResponse(BaseModel):
    """Schema for task response"""
    id: int
    title: str
    description: Optional[str]
    completed: bool
    user_id: int
    created_at: str
    updated_at: str

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": 1,
                "title": "Complete project documentation",
                "description": "Write comprehensive documentation for the API",
                "completed": False,
                "user_id": 1,
                "created_at": "2024-01-01T10:00:00Z",
                "updated_at": "2024-01-01T10:00:00Z"
            }
        }
    )


class TaskListResponse(BaseModel):
    """Schema for paginated task list response"""
    tasks: List[TaskResponse]
    total: int
    skip: int
    limit: int
    has_next: bool

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "tasks": [],
                "total": 50,
                "skip": 0,
                "limit": 10,
                "has_next": True
            }
        }
    )


# Helper Functions
async def get_task_by_id(
    task_id: int,
    user_id: int,
    db: Session
) -> Task:
    """
    Retrieve a task by ID and validate ownership
    
    Args:
        task_id: The task ID to retrieve
        user_id: The current user's ID
        db: Database session
        
    Returns:
        Task: The requested task
        
    Raises:
        HTTPException: 404 if task not found, 403 if not owned by user
    """
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        
        if not task:
            raise HTTPException(
                status_code=404,
                detail=f"Task with id {task_id} not found"
            )
        
        if task.user_id != user_id:
            raise HTTPException(
                status_code=403,
                detail="Not authorized to access this task"
            )
        
        return task
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail="Database error occurred while retrieving task"
        )


# API Endpoints
@router.get("/", response_model=TaskListResponse)
async def get_tasks(
    skip: int = Query(default=0, ge=0, description="Number of tasks to skip"),
    limit: int = Query(default=10, ge=1, le=100, description="Number of tasks to return"),
    completed: Optional[bool] = Query(default=None, description="Filter by completion status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> TaskListResponse:
    """
    Retrieve a paginated list of tasks for the current user
    
    - **skip**: Number of tasks to skip (for pagination)
    - **limit**: Maximum number of tasks to return (1-100)
    - **completed**: Filter by completion status (true/false/null for all)
    """
    try:
        # Build base query filtered by user
        query = db.query(Task).filter(Task.user_id == current_user.id)
        
        # Apply completion status filter if provided
        if completed is not None:
            query = query.filter(Task.completed == completed)
        
        # Get total count for pagination info
        total = query.count()
        
        # Apply pagination and ordering
        tasks = (
            query
            .order_by(Task.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
        
        # Convert to response format
        task_responses = [
            TaskResponse(
                id=task.id,
                title=task.title,
                description=task.description,
                completed=task.completed,
                user_id=task.user_id,
                created_at=task.created_at.isoformat(),
                updated_at=task.updated_at.isoformat()
            )
            for task in tasks
        ]
        
        return TaskListResponse(
            tasks=task_responses,
            total=total,
            skip=skip,
            limit=limit,
            has_next=skip + limit < total
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail="Database error occurred while retrieving tasks"
        )


@router.post("/", response_model=TaskResponse, status_code=201)
async def create_task(
    task_data: TaskCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> TaskResponse:
    """
    Create a new task for the current user
    
    - **title**: Task title (required, 1-200 characters)
    - **description**: Task description (optional, max 1000 characters)
    - **completed**: Task completion status (default: false)
    """
    try:
        # Create new task instance
        new_task = Task(
            title=task_data.title,
            description=task_data.description,
            completed=task_data.completed,
            user_id=current_user.id
        )
        
        # Add to database
        db.add(new_task)
        db.commit()
        db.refresh(new_task)
        
        return TaskResponse(
            id=new_task.id,
            title=new_task.title,
            description=new_task.description,
            completed=new_task.completed,
            user_id=new_task.user_id,
            created_at=new_task.created_at.isoformat(),
            updated_at=new_task.updated_at.isoformat()
        )
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Database error occurred while creating task"
        )


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> TaskResponse:
    """
    Retrieve a specific task by ID
    
    - **task_id**: The ID of the task to retrieve
    """
    task = await get_task_by_id(task_id, current_user.id, db)
    
    return TaskResponse(
        id=task.id,
        title=task.title,
        description=task.description,
        completed=task.completed,
        user_id=task.user_id,
        created_at=task.created_at.isoformat(),
        updated_at=task.updated_at.isoformat()
    )


@router.put("/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: int,
    task_data: TaskUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> TaskResponse:
    """
    Update a specific task by ID
    
    - **task_id**: The ID of the task to update
    - **title**: New task title (optional, 1-200 characters)
    - **description**: New task description (optional, max 1000 characters)
    - **completed**: New task completion status (optional)
    """
    try:
        # Get and validate task ownership
        task = await get_task_by_id(task_id, current_user.id, db)
        
        # Update only provided fields
        update_data = task_data.model_dump(exclude_unset=True)
        
        if not update_data:
            raise HTTPException(
                status_code=422,
                detail="At least one field must be provided for update"
            )
        
        for field, value in update_data.items():
            setattr(task, field, value)
        
        # Commit changes
        db.commit()
        db.refresh(task)
        
        return TaskResponse(
            id=task.id,
            title=task.title,
            description=task.description,
            completed=task.completed,
            user_id=task.user_id,
            created_at=task.created_at.isoformat(),
            updated_at=task.updated_at.isoformat()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Database error occurred while updating task"
        )


@router.delete("/{task_id}", status_code=200)
async def delete_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> dict:
    """
    Delete a specific task by ID
    
    - **task_id**: The ID of the task to delete
    """
    try:
        # Get and validate task ownership
        task = await get_task_by_id(task_id, current_user.id, db)
        
        # Delete the task
        db.delete(task)
        db.commit()
        
        return {
            "message": f"Task {task_id} has been successfully deleted",
            "deleted_task_id": task_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Database error occurred while deleting task"
        )