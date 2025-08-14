from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Index
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from models.user import User
from database import db


class Task(db.Model):
    """
    Task model representing user tasks with automatic timestamp handling.
    
    Attributes:
        id: Primary key identifier
        title: Required task title
        description: Optional task description
        completed: Boolean status (default False)
        user_id: Foreign key reference to User
        created_at: Automatic creation timestamp
        updated_at: Automatic update timestamp
    """
    
    __tablename__ = 'tasks'
    
    # Primary key
    id = Column(Integer, primary_key=True)
    
    # Task fields
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    completed = Column(Boolean, default=False, nullable=False)
    
    # Foreign key relationship
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    
    # Automatic timestamps
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )
    
    # Relationship to User model
    user = relationship("User", back_populates="tasks")
    
    # Database indexes for performance optimization
    __table_args__ = (
        Index('idx_user_tasks', 'user_id'),
        Index('idx_task_status', 'completed'),
        Index('idx_task_created', 'created_at'),
    )
    
    def __repr__(self) -> str:
        return f"<Task(id={self.id}, title='{self.title}', completed={self.completed})>"
    
    def to_dict(self) -> dict:
        """Convert task instance to dictionary representation."""
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'completed': self.completed,
            'user_id': self.user_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }