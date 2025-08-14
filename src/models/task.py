from datetime import datetime
from sqlalchemy import Index
from ..database import db
from .user import User


class Task(db.Model):
    """
    Task model representing user tasks in the application.
    
    Attributes:
        id: Primary key identifier
        title: Task title (required)
        description: Detailed task description
        completed: Task completion status
        user_id: Foreign key reference to User
        created_at: Timestamp when task was created
        updated_at: Timestamp when task was last modified
    """
    
    __tablename__ = 'tasks'
    
    # Primary key
    id = db.Column(db.Integer, primary_key=True)
    
    # Task fields
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    completed = db.Column(db.Boolean, nullable=False, default=False)
    
    # Foreign key relationship
    user_id = db.Column(
        db.Integer, 
        db.ForeignKey('users.id', ondelete='CASCADE'), 
        nullable=False
    )
    
    # Timestamp fields
    created_at = db.Column(
        db.DateTime, 
        nullable=False, 
        default=datetime.utcnow
    )
    updated_at = db.Column(
        db.DateTime, 
        nullable=False, 
        default=datetime.utcnow, 
        onupdate=datetime.utcnow
    )
    
    # Relationship to User model
    user = db.relationship(
        'User', 
        backref=db.backref('tasks', lazy=True, cascade='all, delete-orphan')
    )
    
    # Database indexes for query optimization
    __table_args__ = (
        Index('idx_task_user_id', 'user_id'),
        Index('idx_task_completed', 'completed'),
        Index('idx_task_user_completed', 'user_id', 'completed'),
        Index('idx_task_created_at', 'created_at'),
    )
    
    def __repr__(self):
        """String representation of Task object for debugging."""
        return f'<Task {self.id}: {self.title[:30]}{"..." if len(self.title) > 30 else ""}>'
    
    def __str__(self):
        """Human-readable string representation."""
        status = "✓" if self.completed else "○"
        return f'{status} {self.title}'
    
    def to_dict(self):
        """Convert Task object to dictionary for JSON serialization."""
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'completed': self.completed,
            'user_id': self.user_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
    
    @classmethod
    def get_user_tasks(cls, user_id, completed=None):
        """
        Get tasks for a specific user, optionally filtered by completion status.
        
        Args:
            user_id: ID of the user
            completed: Optional boolean to filter by completion status
            
        Returns:
            Query object for user's tasks
        """
        query = cls.query.filter_by(user_id=user_id)
        if completed is not None:
            query = query.filter_by(completed=completed)
        return query.order_by(cls.created_at.desc())
    
    def mark_completed(self):
        """Mark task as completed."""
        self.completed = True
        db.session.commit()
    
    def mark_incomplete(self):
        """Mark task as incomplete."""
        self.completed = False
        db.session.commit()
    
    def toggle_completion(self):
        """Toggle task completion status."""
        self.completed = not self.completed
        db.session.commit()
        return self.completed