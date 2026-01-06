"""
Authentication Module
Handles user registration, login, and API key management
"""

import secrets
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta
from typing import Optional, Dict
from pydantic import BaseModel, EmailStr
import jwt
import logging

logger = logging.getLogger(__name__)

# File for persisting auth data
AUTH_DATA_FILE = os.environ.get("AUTH_DATA_FILE", "data/auth.json")

# Secret key for JWT (should be in environment variable in production)
JWT_SECRET = "change-this-in-production-use-env-var"
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24


class User(BaseModel):
    """User model"""
    id: str
    email: str
    password_hash: str
    api_key: str
    created_at: datetime
    last_login: Optional[datetime] = None


class UserCreate(BaseModel):
    """User creation request"""
    email: EmailStr
    password: str


class UserLogin(BaseModel):
    """User login request"""
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Token response"""
    access_token: str
    token_type: str = "bearer"
    api_key: str
    user_id: str
    expires_in: int = JWT_EXPIRATION_HOURS * 3600


class AuthManager:
    """
    Manages user authentication
    Persists to JSON file for durability across restarts
    """

    def __init__(self):
        # In-memory storage (backed by JSON file)
        self.users: Dict[str, User] = {}
        self.api_keys: Dict[str, str] = {}  # api_key -> user_id
        self.emails: Dict[str, str] = {}    # email -> user_id

        # Load existing data
        self._load_data()

    def _load_data(self):
        """Load auth data from JSON file"""
        try:
            if os.path.exists(AUTH_DATA_FILE):
                with open(AUTH_DATA_FILE, 'r') as f:
                    data = json.load(f)

                for user_data in data.get("users", []):
                    user = User(
                        id=user_data["id"],
                        email=user_data["email"],
                        password_hash=user_data["password_hash"],
                        api_key=user_data["api_key"],
                        created_at=datetime.fromisoformat(user_data["created_at"]),
                        last_login=datetime.fromisoformat(user_data["last_login"]) if user_data.get("last_login") else None
                    )
                    self.users[user.id] = user
                    self.api_keys[user.api_key] = user.id
                    self.emails[user.email] = user.id

                logger.info(f"Loaded {len(self.users)} users from {AUTH_DATA_FILE}")
        except Exception as e:
            logger.warning(f"Could not load auth data: {e}")

    def _save_data(self):
        """Save auth data to JSON file"""
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(AUTH_DATA_FILE) or ".", exist_ok=True)

            data = {
                "users": [
                    {
                        "id": user.id,
                        "email": user.email,
                        "password_hash": user.password_hash,
                        "api_key": user.api_key,
                        "created_at": user.created_at.isoformat(),
                        "last_login": user.last_login.isoformat() if user.last_login else None
                    }
                    for user in self.users.values()
                ]
            }

            with open(AUTH_DATA_FILE, 'w') as f:
                json.dump(data, f, indent=2)

            logger.debug(f"Saved {len(self.users)} users to {AUTH_DATA_FILE}")
        except Exception as e:
            logger.error(f"Could not save auth data: {e}")

    def _hash_password(self, password: str) -> str:
        """Hash a password using SHA-256 with salt"""
        salt = secrets.token_hex(16)
        hash_obj = hashlib.sha256((password + salt).encode())
        return f"{salt}:{hash_obj.hexdigest()}"

    def _verify_password(self, password: str, password_hash: str) -> bool:
        """Verify a password against its hash"""
        try:
            salt, hash_value = password_hash.split(":")
            new_hash = hashlib.sha256((password + salt).encode()).hexdigest()
            return hmac.compare_digest(hash_value, new_hash)
        except Exception:
            return False

    def _generate_api_key(self) -> str:
        """Generate a secure API key"""
        return f"blender_{secrets.token_urlsafe(32)}"

    def _generate_user_id(self) -> str:
        """Generate a unique user ID"""
        return secrets.token_hex(16)

    def _create_jwt_token(self, user_id: str) -> str:
        """Create a JWT token for a user"""
        expiration = datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS)
        payload = {
            "sub": user_id,
            "exp": expiration,
            "iat": datetime.utcnow()
        }
        return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

    def _verify_jwt_token(self, token: str) -> Optional[str]:
        """Verify a JWT token and return user_id"""
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            return payload.get("sub")
        except jwt.ExpiredSignatureError:
            logger.warning("JWT token expired")
            return None
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid JWT token: {e}")
            return None

    async def register(self, data: UserCreate) -> TokenResponse:
        """Register a new user"""
        # Check if email already exists
        if data.email.lower() in self.emails:
            raise ValueError("Email already registered")

        # Create user
        user_id = self._generate_user_id()
        api_key = self._generate_api_key()
        password_hash = self._hash_password(data.password)

        user = User(
            id=user_id,
            email=data.email.lower(),
            password_hash=password_hash,
            api_key=api_key,
            created_at=datetime.now()
        )

        # Store user
        self.users[user_id] = user
        self.api_keys[api_key] = user_id
        self.emails[data.email.lower()] = user_id

        # Persist to file
        self._save_data()

        logger.info(f"Registered new user: {user_id}")

        # Generate token
        access_token = self._create_jwt_token(user_id)

        return TokenResponse(
            access_token=access_token,
            api_key=api_key,
            user_id=user_id
        )

    async def login(self, data: UserLogin) -> TokenResponse:
        """Login a user"""
        email = data.email.lower()

        # Find user
        user_id = self.emails.get(email)
        if not user_id:
            raise ValueError("Invalid email or password")

        user = self.users.get(user_id)
        if not user:
            raise ValueError("Invalid email or password")

        # Verify password
        if not self._verify_password(data.password, user.password_hash):
            raise ValueError("Invalid email or password")

        # Update last login
        user.last_login = datetime.now()

        # Persist to file
        self._save_data()

        logger.info(f"User logged in: {user_id}")

        # Generate token
        access_token = self._create_jwt_token(user_id)

        return TokenResponse(
            access_token=access_token,
            api_key=user.api_key,
            user_id=user_id
        )

    async def verify_token(self, token: str) -> Optional[User]:
        """Verify a JWT token and return the user"""
        user_id = self._verify_jwt_token(token)
        if user_id:
            return self.users.get(user_id)
        return None

    async def verify_api_key(self, api_key: str) -> Optional[User]:
        """Verify an API key and return the user"""
        user_id = self.api_keys.get(api_key)
        if user_id:
            return self.users.get(user_id)
        return None

    async def get_user(self, user_id: str) -> Optional[User]:
        """Get a user by ID"""
        return self.users.get(user_id)

    async def regenerate_api_key(self, user_id: str) -> str:
        """Regenerate API key for a user"""
        user = self.users.get(user_id)
        if not user:
            raise ValueError("User not found")

        # Remove old API key
        old_key = user.api_key
        if old_key in self.api_keys:
            del self.api_keys[old_key]

        # Generate new key
        new_key = self._generate_api_key()
        user.api_key = new_key
        self.api_keys[new_key] = user_id

        # Persist to file
        self._save_data()

        logger.info(f"Regenerated API key for user: {user_id}")

        return new_key
