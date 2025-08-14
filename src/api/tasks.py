# File: api/tasks.py
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime

# Import from relative paths
from ..models.task import Task
from ..models.user import User
from ..core.database import get_db

# Security
security = HTTPBearer()

# Router setup
router = APIRouter(prefix="/tasks", tags=["tasks"])


# Pydantic Models
class TaskCreate(BaseModel):
    """Schema for creating a new task"""
    title: str = Field(..., min_length=1, max_length=200, description="Task title")
    description: Optional[str] = Field(None, max_length=1000, description="Task description")
    due_date: Optional[datetime] = Field(None, description="Task due date")

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class TaskUpdate(BaseModel):
    """Schema for updating an existing task"""
    title: Optional[str] = Field(None, min_length=1, max_length=200, description="Task title")
    description: Optional[str] = Field(None, max_length=1000, description="Task description")
    due_date: Optional[datetime] = Field(None, description="Task due date")
    completed: Optional[bool] = Field(None, description="Task completion status")

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class TaskResponse(BaseModel):
    """Schema for task API responses"""
    id: int
    title: str
    description: Optional[str]
    due_date: Optional[datetime]
    completed: bool
    created_at: datetime
    updated_at: datetime
    user_id: int

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class TaskListResponse(BaseModel):
    """Schema for paginated task list responses"""
    tasks: List[TaskResponse]
    total: int
    limit: int
    offset: int
    has_next: bool
    has_previous: bool

    class Config:
        from_attributes = True


# Dependency to get current user (placeholder - implement based on your auth system)
async def get_current_user(
    token: str = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """
    Get current authenticated user from token.
    This is a placeholder - implement based on your authentication system.
    """
    # TODO: Implement actual token validation and user retrieval
    # For now, this is a placeholder that should be replaced with your auth logic
    try:
        # Example implementation - replace with your actual auth logic
        user = db.query(User).filter(User.id == 1).first()  # Placeholder
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return user
    except SQLAlchemyError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error during authentication"
        )


def get_task_by_id_and_user(task_id: int, user_id: int, db: Session) -> Task:
    """
    Get task by ID and validate ownership.
    
    Args:
        task_id: Task ID to retrieve
        user_id: User ID for ownership validation
        db: Database session
        
    Returns:
        Task object if found and owned by user
        
    Raises:
        HTTPException: If task not found or access denied
    """
    try:
        task = db.query(Task).filter(
            Task.id == task_id,
            Task.user_id == user_id
        ).first()
        
        if not task:
            # Check if task exists but belongs to different user
            task_exists = db.query(Task).filter(Task.id == task_id).first()
            if task_exists:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied: Task belongs to another user"
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Task with ID {task_id} not found"
                )
        
        return task
    except SQLAlchemyError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error while retrieving task"
        )


# API Endpoints
@router.get("/", response_model=TaskListResponse, status_code=status.HTTP_200_OK)
async def list_tasks(
    limit: int = Query(default=20, ge=1, le=100, description="Number of tasks to return"),
    offset: int = Query(default=0, ge=0, description="Number of tasks to skip"),
    completed: Optional[bool] = Query(default=None, description="Filter by completion status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> TaskListResponse:
    """
    Retrieve a paginated list of tasks for the authenticated user.
    
    - **limit**: Maximum number of tasks to return (1-100)
    - **offset**: Number of tasks to skip for pagination
    - **completed**: Optional filter by completion status
    
    Returns paginated list with metadata.
    """
    try:
        # Build query with user filter
        query = db.query(Task).filter(Task.user_id == current_user.id)
        
        # Apply completion status filter if provided
        if completed is not None:
            query = query.filter(Task.completed == completed)
        
        # Get total count for pagination metadata
        total = query.count()
        
        # Apply pagination and ordering
        tasks = query.order_by(Task.created_at.desc()).offset(offset).limit(limit).all()
        
        # Calculate pagination metadata
        has_next = offset + limit < total
        has_previous = offset > 0
        
        return TaskListResponse(
            tasks=tasks,
            total=total,
            limit=limit,
            offset=offset,
            has_next=has_next,
            has_previous=has_previous
        )
        
    except SQLAlchemyError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error while retrieving tasks"
        )


@router.post("/", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    task_data: TaskCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> TaskResponse:
    """
    Create a new task for the authenticated user.
    
    - **title**: Task title (required, 1-200 characters)
    - **description**: Optional task description (max 1000 characters)
    - **due_date**: Optional due date in ISO format
    
    Returns the created task with generated ID and timestamps.
    """
    try:
        # Create new task instance
        new_task = Task(
            title=task_data.title,
            description=task_data.description,
            due_date=task_data.due_date,
            user_id=current_user.id,
            completed=False
        )
        
        # Add to database
        db.add(new_task)
        db.commit()
        db.refresh(new_task)
        
        return TaskResponse.from_orm(new_task)
        
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error while creating task"
        )


@router.get("/{task_id}", response_model=TaskResponse, status_code=status.HTTP_200_OK)
async def get_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> TaskResponse:
    """
    Retrieve a specific task by ID.
    
    - **task_id**: Unique identifier of the task
    
    Returns the task if it exists and belongs to the authenticated user.
    Raises 404 if task not found, 403 if access denied.
    """
    task = get_task_by_id_and_user(task_id, current_user.id, db)
    return TaskResponse.from_orm(task)


@router.put("/{task_id}", response_model=TaskResponse, status_code=status.HTTP_200_OK)
async def update_task(
    task_id: int,
    task_update: TaskUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> TaskResponse:
    """
    Update an existing task.
    
    - **task_id**: Unique identifier of the task
    - **title**: Optional new title (1-200 characters)
    - **description**: Optional new description (max 1000 characters)
    - **due_date**: Optional new due date in ISO format
    - **completed**: Optional completion status
    
    Performs partial updates - only provided fields are updated.
    Returns the updated task.
    """
    # Get existing task and validate ownership
    task = get_task_by_id_and_user(task_id, current_user.id, db)
    
    try:
        # Update only provided fields
        update_data = task_update.dict(exclude_unset=True)
        
        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="No fields provided for update"
            )
        
        for field, value in update_data.items():
            setattr(task, field, value)
        
        # Update timestamp
        task.updated_at = datetime.utcnow()
        
        db.commit()
        db.refresh(task)
        
        return TaskResponse.from_orm(task)
        
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error while updating task"
        )


@router.delete("/{task_id}", status_code=status.HTTP_200_OK)
async def delete_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> dict:
    """
    Delete a specific task.
    
    - **task_id**: Unique identifier of the task to delete
    
    Returns success message if task was deleted.
    Raises 404 if task not found, 403 if access denied.
    """
    # Get existing task and validate ownership
    task = get_task_by_id_and_user(task_id, current_user.id, db)
    
    try:
        db.delete(task)
        db.commit()
        
        return {
            "message": f"Task {task_id} deleted successfully",
            "deleted_task_id": task_id
        }
        
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error while deleting task"
        )


# Health check endpoint for the tasks module
@router.get("/health", status_code=status.HTTP_200_OK)
async def tasks_health_check() -> dict:
    """
    Health check endpoint for the tasks API module.
    """
    return {
        "status": "healthy",
        "module": "tasks",
        "timestamp": datetime.utcnow().isoformat()
    }