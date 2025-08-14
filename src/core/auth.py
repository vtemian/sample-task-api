"""
Authentication and Authorization Utilities Module

This module provides comprehensive authentication and authorization functionality
for the FastAPI application, including JWT token management, password hashing,
and user authentication with security best practices.

Security Features:
- JWT token generation and validation with HS256 algorithm
- Bcrypt password hashing with secure salt rounds
- Timing-attack resistant password verification
- OAuth2 password bearer token scheme
- Proper token expiration and validation
- Rate limiting considerations (implement at router level)
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Optional, Union, Annotated, Dict, Any

# FastAPI imports
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

# JWT and cryptography
from jose import JWTError, ExpiredSignatureError, jwt
from passlib.context import CryptContext
from passlib.exc import UnknownHashError

# Database and models
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

# Local imports
from ..models.user import User
from .database import get_db

# Configure logging (avoid logging sensitive data)
logger = logging.getLogger(__name__)

# Security Configuration
# Load from environment with validation
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise ValueError(
        "SECRET_KEY environment variable is required for JWT token generation. "
        "Please set a secure random string as SECRET_KEY."
    )

ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

# Password hashing context with bcrypt
# Using bcrypt with automatic salt generation and secure rounds
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=12  # Secure number of rounds for bcrypt
)

# OAuth2 scheme for token extraction
# tokenUrl should match your login endpoint
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="auth/login",
    scheme_name="JWT"
)

# Exception for authentication failures
credentials_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)

# Exception for inactive users
inactive_user_exception = HTTPException(
    status_code=status.HTTP_400_BAD_REQUEST,
    detail="Inactive user account"
)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain password against a hashed password using timing-attack resistant comparison.
    
    Args:
        plain_password (str): The plain text password to verify
        hashed_password (str): The hashed password to compare against
        
    Returns:
        bool: True if password matches, False otherwise
        
    Security Notes:
        - Uses constant-time comparison to prevent timing attacks
        - Handles hash format validation gracefully
        - Never logs password data
    """
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except UnknownHashError:
        # Handle invalid hash format gracefully
        logger.warning("Invalid hash format encountered during password verification")
        return False
    except Exception as e:
        # Log unexpected errors without exposing sensitive data
        logger.error(f"Unexpected error during password verification: {type(e).__name__}")
        return False


def get_password_hash(password: str) -> str:
    """
    Generate a secure hash for a password using bcrypt with automatic salt generation.
    
    Args:
        password (str): The plain text password to hash
        
    Returns:
        str: The hashed password with salt
        
    Security Notes:
        - Uses bcrypt with 12 rounds for secure hashing
        - Automatically generates unique salt for each password
        - Salt is embedded in the returned hash
    """
    try:
        return pwd_context.hash(password)
    except Exception as e:
        logger.error(f"Error generating password hash: {type(e).__name__}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error processing password"
        )


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT access token with specified data and expiration.
    
    Args:
        data (Dict[str, Any]): The data to encode in the token (typically user info)
        expires_delta (Optional[timedelta]): Custom expiration time, defaults to ACCESS_TOKEN_EXPIRE_MINUTES
        
    Returns:
        str: The encoded JWT token
        
    Raises:
        HTTPException: If token creation fails
        
    Security Notes:
        - Uses HS256 algorithm for signing
        - Includes proper expiration validation
        - Subject (sub) claim should contain user identifier
    """
    try:
        to_encode = data.copy()
        
        # Set expiration time
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        
        # Add standard JWT claims
        to_encode.update({
            "exp": expire,
            "iat": datetime.utcnow(),  # Issued at
            "type": "access"  # Token type for additional validation
        })
        
        # Encode the token
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        return encoded_jwt
        
    except Exception as e:
        logger.error(f"Error creating access token: {type(e).__name__}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error creating access token"
        )


def decode_token(token: str) -> Dict[str, Any]:
    """
    Decode and validate a JWT token.
    
    Args:
        token (str): The JWT token to decode
        
    Returns:
        Dict[str, Any]: The decoded token payload
        
    Raises:
        HTTPException: If token is invalid, expired, or malformed
        
    Security Notes:
        - Validates token signature and expiration
        - Checks for required claims (sub)
        - Handles various JWT error conditions
    """
    try:
        # Decode the token
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        
        # Validate required claims
        user_id: str = payload.get("sub")
        if user_id is None:
            logger.warning("Token missing required 'sub' claim")
            raise credentials_exception
            
        # Additional validation for token type if implemented
        token_type: str = payload.get("type")
        if token_type != "access":
            logger.warning(f"Invalid token type: {token_type}")
            raise credentials_exception
            
        return payload
        
    except ExpiredSignatureError:
        logger.info("Expired token presented")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except JWTError as e:
        logger.warning(f"JWT validation error: {type(e).__name__}")
        raise credentials_exception
    except Exception as e:
        logger.error(f"Unexpected error decoding token: {type(e).__name__}")
        raise credentials_exception


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db)
) -> User:
    """
    Get the current authenticated user from JWT token.
    
    Args:
        token (str): JWT token from Authorization header
        db (Session): Database session dependency
        
    Returns:
        User: The authenticated user object
        
    Raises:
        HTTPException: If token is invalid or user not found
        
    Security Notes:
        - Validates token and extracts user information
        - Performs database lookup to ensure user still exists
        - Handles database connection errors gracefully
    """
    try:
        # Decode and validate the token
        payload = decode_token(token)
        user_id: str = payload.get("sub")
        
        # Query user from database
        user = db.query(User).filter(User.id == int(user_id)).first()
        if user is None:
            logger.warning(f"User not found for token subject: {user_id}")
            raise credentials_exception
            
        return user
        
    except HTTPException:
        # Re-raise HTTP exceptions (from decode_token or user validation)
        raise
    except SQLAlchemyError as e:
        logger.error(f"Database error during user lookup: {type(e).__name__}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error during authentication"
        )
    except ValueError as e:
        # Handle invalid user_id format
        logger.warning(f"Invalid user ID format in token: {e}")
        raise credentials_exception
    except Exception as e:
        logger.error(f"Unexpected error getting current user: {type(e).__name__}")
        raise credentials_exception


async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)]
) -> User:
    """
    Get the current authenticated and active user.
    
    Args:
        current_user (User): The current user from get_current_user dependency
        
    Returns:
        User: The authenticated and active user object
        
    Raises:
        HTTPException: If user account is inactive
        
    Security Notes:
        - Ensures user account is active before granting access
        - Provides clear error message for inactive accounts
        - Can be extended to check other user status fields
    """
    if not current_user.is_active:
        logger.info(f"Inactive user attempted access: {current_user.id}")
        raise inactive_user_exception
        
    return current_user


def authenticate_user(db: Session, email: str, password: str) -> Optional[User]:
    """
    Authenticate a user with email and password.
    
    Args:
        db (Session): Database session
        email (str): User's email address
        password (str): Plain text password
        
    Returns:
        Optional[User]: User object if authentication successful, None otherwise
        
    Security Notes:
        - Uses timing-attack resistant password verification
        - Handles database errors gracefully
        - Never logs password information
        - Returns None for both invalid user and invalid password (prevents user enumeration)
    """
    try:
        # Query user by email
        user = db.query(User).filter(User.email == email).first()
        if not user:
            # Perform dummy password verification to prevent timing attacks
            verify_password("dummy_password", "$2b$12$dummy.hash.to.prevent.timing.attacks")
            logger.info(f"Authentication attempt for non-existent email: {email}")
            return None
            
        # Verify password
        if not verify_password(password, user.hashed_password):
            logger.info(f"Failed password verification for user: {user.id}")
            return None
            
        logger.info(f"Successful authentication for user: {user.id}")
        return user
        
    except SQLAlchemyError as e:
        logger.error(f"Database error during authentication: {type(e).__name__}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error during authentication: {type(e).__name__}")
        return None


def create_refresh_token(user_id: int) -> str:
    """
    Create a refresh token for token renewal.
    
    Args:
        user_id (int): The user ID to encode in the token
        
    Returns:
        str: The encoded refresh token
        
    Security Notes:
        - Longer expiration time than access tokens
        - Different token type for validation
        - Should be stored securely and rotated on use
    """
    try:
        expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
        to_encode = {
            "sub": str(user_id),
            "exp": expire,
            "iat": datetime.utcnow(),
            "type": "refresh"
        }
        
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        return encoded_jwt
        
    except Exception as e:
        logger.error(f"Error creating refresh token: {type(e).__name__}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error creating refresh token"
        )


def validate_refresh_token(token: str) -> Optional[int]:
    """
    Validate a refresh token and extract user ID.
    
    Args:
        token (str): The refresh token to validate
        
    Returns:
        Optional[int]: User ID if token is valid, None otherwise
        
    Security Notes:
        - Validates token type to ensure it's a refresh token
        - Checks expiration and signature
        - Returns None for any validation failure
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        
        # Validate token type
        if payload.get("type") != "refresh":
            return None
            
        user_id = payload.get("sub")
        if user_id is None:
            return None
            
        return int(user_id)
        
    except (JWTError, ValueError, ExpiredSignatureError):
        return None
    except Exception as e:
        logger.error(f"Unexpected error validating refresh token: {type(e).__name__}")
        return None


# Rate limiting considerations:
# Implement rate limiting at the router level for authentication endpoints
# Consider using Redis or in-memory stores for rate limit tracking
# Recommended limits:
# - Login attempts: 5 per minute per IP
# - Token refresh: 10 per minute per user
# - Password reset: 3 per hour per email

# CORS considerations:
# Configure CORS middleware to restrict origins in production
# Ensure credentials are handled properly for cross-origin requests
# Consider using secure, httpOnly cookies for token storage in browsers

# Additional security headers to implement at application level:
# - X-Content-Type-Options: nosniff
# - X-Frame-Options: DENY
# - X-XSS-Protection: 1; mode=block
# - Strict-Transport-Security: max-age=31536000; includeSubDomains