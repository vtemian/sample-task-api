"""
User model module for SQLAlchemy ORM.

This module defines the User model with password hashing, relationships,
and utility methods for user management.
"""

from datetime import datetime
from typing import Dict, Any, Optional, List

import bcrypt
from sqlalchemy import Column, Integer, String, Boolean, DateTime, text
from sqlalchemy.orm import relationship
from sqlalchemy.exc import SQLAlchemyError

# Assuming base declarative class exists
from .base import Base


class User(Base):
    """
    User model for authentication and user management.
    
    Provides secure password hashing, user relationships, and utility methods
    for converting user data to dictionary format while maintaining security.
    """
    
    __tablename__ = 'users'
    
    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    # User credentials and info
    username = Column(
        String(50), 
        unique=True, 
        nullable=False, 
        index=True,
        comment="Unique username for user identification"
    )
    
    email = Column(
        String(255), 
        unique=True, 
        nullable=False, 
        index=True,
        comment="Unique email address for user"
    )
    
    hashed_password = Column(
        String(255), 
        nullable=False,
        comment="Bcrypt hashed password - never store plain text"
    )
    
    # User status and metadata
    is_active = Column(
        Boolean, 
        nullable=False, 
        default=True,
        server_default=text('true'),
        comment="Soft deletion flag - false means user is deactivated"
    )
    
    created_at = Column(
        DateTime, 
        nullable=False, 
        default=datetime.utcnow,
        server_default=text('CURRENT_TIMESTAMP'),
        comment="Timestamp when user was created"
    )
    
    # Relationships
    tasks = relationship(
        "Task", 
        back_populates="user",
        lazy="dynamic",
        cascade="all, delete-orphan",
        comment="One-to-many relationship with Task model"
    )
    
    def set_password(self, password: str) -> None:
        """
        Hash and set the user's password using bcrypt.
        
        Args:
            password (str): Plain text password to hash and store
            
        Raises:
            ValueError: If password is None or empty
            RuntimeError: If bcrypt hashing fails
        """
        if not password:
            raise ValueError("Password cannot be None or empty")
        
        try:
            # Generate salt and hash password
            salt = bcrypt.gensalt()
            hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
            self.hashed_password = hashed.decode('utf-8')
        except Exception as e:
            raise RuntimeError(f"Failed to hash password: {str(e)}")
    
    def check_password(self, password: str) -> bool:
        """
        Verify a password against the stored hash.
        
        Args:
            password (str): Plain text password to verify
            
        Returns:
            bool: True if password matches, False otherwise
            
        Raises:
            ValueError: If password is None or empty
        """
        if not password:
            raise ValueError("Password cannot be None or empty")
        
        if not self.hashed_password:
            return False
        
        try:
            return bcrypt.checkpw(
                password.encode('utf-8'), 
                self.hashed_password.encode('utf-8')
            )
        except Exception:
            # Log the exception in production, but don't expose details
            return False
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert user instance to dictionary format.
        
        Excludes sensitive fields like hashed_password for security.
        Formats datetime fields as ISO strings for JSON serialization.
        
        Returns:
            Dict[str, Any]: Dictionary representation of user data
        """
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
    
    def get_active_tasks_count(self) -> int:
        """
        Get count of active tasks for this user.
        
        Returns:
            int: Number of active tasks
        """
        try:
            return self.tasks.filter_by(is_completed=False).count()
        except SQLAlchemyError:
            return 0
    
    def deactivate(self) -> None:
        """
        Soft delete the user by setting is_active to False.
        
        This method implements soft deletion - the user record remains
        in the database but is marked as inactive.
        """
        self.is_active = False
    
    def activate(self) -> None:
        """
        Reactivate a previously deactivated user.
        """
        self.is_active = True
    
    def __repr__(self) -> str:
        """
        String representation of User instance.
        
        Returns:
            str: Safe string representation without sensitive data
        """
        return f"<User(id={self.id}, username='{self.username}', email='{self.email}', active={self.is_active})>"
    
    def __str__(self) -> str:
        """
        Human-readable string representation.
        
        Returns:
            str: User's username
        """
        return self.username
    
    @classmethod
    def create_user(cls, username: str, email: str, password: str, **kwargs) -> 'User':
        """
        Class method to create a new user with hashed password.
        
        Args:
            username (str): Unique username
            email (str): Unique email address
            password (str): Plain text password (will be hashed)
            **kwargs: Additional user attributes
            
        Returns:
            User: New user instance with hashed password
            
        Raises:
            ValueError: If required fields are missing or invalid
        """
        if not all([username, email, password]):
            raise ValueError("Username, email, and password are required")
        
        user = cls(username=username, email=email, **kwargs)
        user.set_password(password)
        return user