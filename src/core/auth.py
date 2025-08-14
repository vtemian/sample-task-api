"""
Core authentication and authorization module for FastAPI applications.

This module provides comprehensive JWT-based authentication with OAuth2 password bearer flow,
secure password hashing using bcrypt, and role-based access control foundations.
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta
from typing import Optional, Union, Dict, Any
import os
import secrets
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

# Assume these imports exist in your project
# from models.user import User
# from .database import get_db

# Configuration constants
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    # Generate a secure random key for development, but warn about it
    SECRET_KEY = secrets.token_urlsafe(32)
    print("WARNING: SECRET_KEY not found in environment variables. Using generated key for development only.")
    print("For production, set SECRET_KEY environment variable to a secure random string.")

ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

# Password context for bcrypt hashing
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=12  # Secure default for bcrypt rounds
)

# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Standard credentials exception
credentials_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain password against its hash using constant-time comparison.
    
    Args:
        plain_password: The plain text password to verify
        hashed_password: The hashed password to compare against
        
    Returns:
        bool: True if password matches, False otherwise
    """
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception:
        # Return False for any hashing errors to prevent information leakage
        return False


def get_password_hash(password: str) -> str:
    """
    Generate a secure hash for the given password.
    
    Args:
        password: The plain text password to hash
        
    Returns:
        str: The hashed password
        
    Raises:
        ValueError: If password is empty or None
    """
    if not password:
        raise ValueError("Password cannot be empty")
    
    return pwd_context.hash(password)


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT access token with the provided data.
    
    Args:
        data: Dictionary containing the claims to encode in the token
        expires_delta: Optional custom expiration time
        
    Returns:
        str: The encoded JWT token
        
    Raises:
        ValueError: If required data is missing
    """
    if not data:
        raise ValueError("Token data cannot be empty")
    
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire, "iat": datetime.utcnow()})
    
    try:
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        return encoded_jwt
    except Exception as e:
        raise ValueError(f"Failed to create token: {str(e)}")


def create_refresh_token(data: Dict[str, Any]) -> str:
    """
    Create a JWT refresh token with extended expiration.
    
    Args:
        data: Dictionary containing the claims to encode in the token
        
    Returns:
        str: The encoded JWT refresh token
    """
    expires_delta = timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode = data.copy()
    to_encode.update({"type": "refresh"})
    
    return create_access_token(to_encode, expires_delta)


def decode_token(token: str) -> Dict[str, Any]:
    """
    Decode and validate a JWT token.
    
    Args:
        token: The JWT token to decode
        
    Returns:
        dict: The decoded token payload
        
    Raises:
        HTTPException: If token is invalid, expired, or malformed
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        
        # Validate required fields
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
            
        # Check if token has expired (jose handles this, but explicit check for clarity)
        exp = payload.get("exp")
        if exp is None or datetime.utcnow() > datetime.fromtimestamp(exp):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired",
                headers={"WWW-Authenticate": "Bearer"},
            )
            
        return payload
        
    except JWTError as e:
        # Handle specific JWT errors
        error_msg = str(e).lower()
        if "expired" in error_msg:
            detail = "Token has expired"
        elif "signature" in error_msg:
            detail = "Invalid token signature"
        else:
            detail = "Could not validate credentials"
            
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception:
        raise credentials_exception


def authenticate_user(db: Session, email: str, password: str):  # -> Optional[User]
    """
    Authenticate a user by email/username and password with timing attack protection.
    
    Args:
        db: Database session
        email: User's email or username
        password: Plain text password
        
    Returns:
        User: The authenticated user object, or None if authentication fails
    """
    if not email or not password:
        return None
    
    try:
        # Try to find user by email first, then by username
        # Note: Adjust this query based on your User model structure
        user = db.query(User).filter(
            (User.email == email) | (User.username == email)
        ).first()
        
        # Always perform password verification to prevent timing attacks
        # even if user doesn't exist
        if user:
            password_valid = verify_password(password, user.hashed_password)
        else:
            # Perform a dummy hash operation to maintain consistent timing
            verify_password(password, "$2b$12$dummy.hash.to.prevent.timing.attacks")
            password_valid = False
        
        if user and password_valid and user.is_active:
            return user
            
        return None
        
    except SQLAlchemyError:
        # Log database errors (in production, use proper logging)
        # Don't expose database errors to the client
        return None
    except Exception:
        # Handle any other unexpected errors
        return None


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):  # -> User
    """
    FastAPI dependency to get the current authenticated user from JWT token.
    
    Args:
        token: JWT token from Authorization header
        db: Database session
        
    Returns:
        User: The current authenticated user
        
    Raises:
        HTTPException: If token is invalid or user not found
    """
    try:
        payload = decode_token(token)
        username: str = payload.get("sub")
        
        if username is None:
            raise credentials_exception
            
    except HTTPException:
        # Re-raise HTTP exceptions from decode_token
        raise
    except Exception:
        raise credentials_exception
    
    try:
        # Look up user in database
        user = db.query(User).filter(
            (User.email == username) | (User.username == username)
        ).first()
        
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
                headers={"WWW-Authenticate": "Bearer"},
            )
            
        return user
        
    except SQLAlchemyError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred"
        )
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception:
        raise credentials_exception


def get_current_active_user(
    current_user = Depends(get_current_user)  # current_user: User
):  # -> User
    """
    FastAPI dependency to get the current active user.
    
    Args:
        current_user: The current authenticated user
        
    Returns:
        User: The current active user
        
    Raises:
        HTTPException: If user is inactive
    """
    if not getattr(current_user, 'is_active', True):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )
    return current_user


def require_roles(allowed_roles: list):
    """
    Create a dependency that requires specific user roles.
    
    Args:
        allowed_roles: List of roles that are allowed access
        
    Returns:
        Dependency function that checks user roles
        
    Usage:
        @app.get("/admin")
        def admin_endpoint(user: User = Depends(require_roles(["admin"]))):
            return {"message": "Admin access granted"}
    """
    def role_checker(current_user = Depends(get_current_active_user)):  # current_user: User
        user_roles = getattr(current_user, 'roles', [])
        
        # Handle both string roles and role objects
        if hasattr(user_roles, '__iter__') and not isinstance(user_roles, str):
            user_role_names = [
                role.name if hasattr(role, 'name') else str(role) 
                for role in user_roles
            ]
        else:
            user_role_names = [str(user_roles)] if user_roles else []
        
        if not any(role in allowed_roles for role in user_role_names):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions"
            )
        return current_user
    
    return role_checker


def require_permission(permission: str):
    """
    Create a dependency that requires a specific permission.
    
    Args:
        permission: The required permission string
        
    Returns:
        Dependency function that checks user permissions
    """
    def permission_checker(current_user = Depends(get_current_active_user)):  # current_user: User
        user_permissions = getattr(current_user, 'permissions', [])
        
        # Handle both string permissions and permission objects
        if hasattr(user_permissions, '__iter__') and not isinstance(user_permissions, str):
            user_permission_names = [
                perm.name if hasattr(perm, 'name') else str(perm) 
                for perm in user_permissions
            ]
        else:
            user_permission_names = [str(user_permissions)] if user_permissions else []
        
        if permission not in user_permission_names:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission '{permission}' required"
            )
        return current_user
    
    return permission_checker


def create_token_response(user) -> Dict[str, Any]:  # user: User
    """
    Create a standardized token response for successful authentication.
    
    Args:
        user: The authenticated user
        
    Returns:
        dict: Token response with access token, refresh token, and user info
    """
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    # Create token data
    token_data = {
        "sub": getattr(user, 'email', getattr(user, 'username', str(user.id))),
        "user_id": user.id,
        "roles": [role.name if hasattr(role, 'name') else str(role) 
                 for role in getattr(user, 'roles', [])],
    }
    
    access_token = create_access_token(
        data=token_data,
        expires_delta=access_token_expires
    )
    
    refresh_token = create_refresh_token(data={"sub": token_data["sub"]})
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,  # seconds
        "user": {
            "id": user.id,
            "email": getattr(user, 'email', None),
            "username": getattr(user, 'username', None),
            "is_active": getattr(user, 'is_active', True),
            "roles": [role.name if hasattr(role, 'name') else str(role) 
                     for role in getattr(user, 'roles', [])],
        }
    }


# Utility function for password strength validation
def validate_password_strength(password: str) -> Dict[str, Union[bool, list]]:
    """
    Validate password strength according to common security requirements.
    
    Args:
        password: The password to validate
        
    Returns:
        dict: Validation result with is_valid flag and list of issues
    """
    issues = []
    
    if len(password) < 8:
        issues.append("Password must be at least 8 characters long")
    
    if not any(c.isupper() for c in password):
        issues.append("Password must contain at least one uppercase letter")
    
    if not any(c.islower() for c in password):
        issues.append("Password must contain at least one lowercase letter")
    
    if not any(c.isdigit() for c in password):
        issues.append("Password must contain at least one digit")
    
    if not any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password):
        issues.append("Password must contain at least one special character")
    
    return {
        "is_valid": len(issues) == 0,
        "issues": issues
    }