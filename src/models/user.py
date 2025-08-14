from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import bcrypt
from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    
    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # User credentials and info
    username = Column(String(80), unique=True, nullable=False, index=True)
    email = Column(String(120), unique=True, nullable=False, index=True)
    hashed_password = Column(String(128), nullable=False)
    
    # Status and metadata
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    tasks = relationship(
        "Task",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="dynamic"
    )
    
    def set_password(self, password):
        """
        Hash and set the user's password.
        
        Args:
            password (str): Plain text password to hash
        """
        if not password:
            raise ValueError("Password cannot be empty")
        
        # Ensure password is encoded as bytes for bcrypt
        if isinstance(password, str):
            password = password.encode('utf-8')
        
        # Generate salt and hash password
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password, salt)
        
        # Store as string in database
        self.hashed_password = hashed.decode('utf-8')
    
    def check_password(self, password):
        """
        Verify a plain text password against the stored hash.
        
        Args:
            password (str): Plain text password to verify
            
        Returns:
            bool: True if password matches, False otherwise
        """
        if not password or not self.hashed_password:
            return False
        
        try:
            # Ensure inputs are properly encoded
            if isinstance(password, str):
                password = password.encode('utf-8')
            
            stored_hash = self.hashed_password
            if isinstance(stored_hash, str):
                stored_hash = stored_hash.encode('utf-8')
            
            return bcrypt.checkpw(password, stored_hash)
        except (ValueError, TypeError):
            return False
    
    def to_dict(self):
        """
        Convert user instance to dictionary, excluding sensitive fields.
        
        Returns:
            dict: User data without password-related fields
        """
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
    
    def soft_delete(self):
        """
        Perform soft deletion by setting is_active to False.
        """
        self.is_active = False
    
    def activate(self):
        """
        Reactivate a soft-deleted user.
        """
        self.is_active = True
    
    @classmethod
    def create_user(cls, username, email, password):
        """
        Class method to create a new user with hashed password.
        
        Args:
            username (str): Unique username
            email (str): Unique email address
            password (str): Plain text password
            
        Returns:
            User: New user instance with hashed password
        """
        if not all([username, email, password]):
            raise ValueError("Username, email, and password are required")
        
        user = cls(username=username, email=email)
        user.set_password(password)
        return user
    
    def __repr__(self):
        """
        String representation of User instance for debugging.
        
        Returns:
            str: User representation
        """
        return f"<User(id={self.id}, username='{self.username}', email='{self.email}', is_active={self.is_active})>"
    
    def __str__(self):
        """
        Human-readable string representation.
        
        Returns:
            str: User string representation
        """
        return f"User: {self.username} ({self.email})"