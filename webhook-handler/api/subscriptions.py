"""Subscription API for auto-configuring webhooks"""
from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, Any, List
from pydantic import BaseModel, HttpUrl
from datetime import datetime, timedelta
import httpx
import secrets
from utils.logger import log
from config import settings
from services.webhook_manager import WebhookManager
from db.database import Database
from services.auth import get_api_key

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])

class SubscriptionRequest(BaseModel):
    """Request model for creating subscription"""
    project_type: str  # 'gitlab' or 'sonarqube'
    project_id: str
    project_url: HttpUrl
    access_token: str
    webhook_events: List[str] = ["pipeline", "merge_request", "quality_gate"]
    metadata: Dict[str, Any] = {}

class SubscriptionResponse(BaseModel):
    """Response model for subscription"""
    subscription_id: str
    project_id: str
    webhook_url: str
    webhook_secret: str
    status: str
    expires_at: datetime
    webhook_ids: List[str]

webhook_manager = WebhookManager()
db = Database()

@router.post("/", response_model=SubscriptionResponse)
async def create_subscription(
    request: SubscriptionRequest,
    api_key: str = Depends(get_api_key)
):
    """Create a new webhook subscription for a project"""
    try:
        log.info(f"Creating subscription for {request.project_type} project {request.project_id}")
        
        # Generate unique webhook secret for this subscription
        webhook_secret = secrets.token_urlsafe(32)
        subscription_id = secrets.token_hex(16)
        
        # Prepare webhook URL with subscription ID
        webhook_url = f"{settings.subscription_callback_url}/{request.project_type}/{subscription_id}"
        
        # Configure webhooks based on project type
        webhook_ids = []
        
        if request.project_type == "gitlab":
            webhook_ids = await webhook_manager.setup_gitlab_webhooks(
                project_id=request.project_id,
                project_url=str(request.project_url),
                access_token=request.access_token,
                webhook_url=webhook_url,
                webhook_secret=webhook_secret,
                events=request.webhook_events
            )
        elif request.project_type == "sonarqube":
            webhook_ids = await webhook_manager.setup_sonarqube_webhooks(
                project_key=request.project_id,
                sonarqube_url=str(request.project_url),
                access_token=request.access_token,
                webhook_url=webhook_url,
                webhook_secret=webhook_secret
            )
        else:
            raise HTTPException(status_code=400, detail="Invalid project type")
        
        # Store subscription in database
        expires_at = datetime.utcnow() + timedelta(days=settings.subscription_ttl_days)
        
        await db.create_subscription({
            "subscription_id": subscription_id,
            "project_type": request.project_type,
            "project_id": request.project_id,
            "project_url": str(request.project_url),
            "webhook_url": webhook_url,
            "webhook_secret": webhook_secret,
            "webhook_ids": webhook_ids,
            "status": "active",
            "expires_at": expires_at,
            "metadata": request.metadata,
            "api_key": api_key
        })
        
        log.info(f"Successfully created subscription {subscription_id} with {len(webhook_ids)} webhooks")
        
        return SubscriptionResponse(
            subscription_id=subscription_id,
            project_id=request.project_id,
            webhook_url=webhook_url,
            webhook_secret=webhook_secret,
            status="active",
            expires_at=expires_at,
            webhook_ids=webhook_ids
        )
        
    except Exception as e:
        log.error(f"Failed to create subscription: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{subscription_id}")
async def get_subscription(
    subscription_id: str,
    api_key: str = Depends(get_api_key)
):
    """Get subscription details"""
    subscription = await db.get_subscription(subscription_id)
    
    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription not found")
    
    # Verify ownership
    if subscription.get("api_key") != api_key:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return subscription

@router.get("/")
async def list_subscriptions(
    api_key: str = Depends(get_api_key),
    status: str = "active",
    limit: int = 100
):
    """List all subscriptions for the authenticated user"""
    subscriptions = await db.list_subscriptions(
        api_key=api_key,
        status=status,
        limit=limit
    )
    return subscriptions

@router.delete("/{subscription_id}")
async def delete_subscription(
    subscription_id: str,
    api_key: str = Depends(get_api_key)
):
    """Delete a subscription and remove associated webhooks"""
    try:
        subscription = await db.get_subscription(subscription_id)
        
        if not subscription:
            raise HTTPException(status_code=404, detail="Subscription not found")
        
        # Verify ownership
        if subscription.get("api_key") != api_key:
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Remove webhooks from the source system
        if subscription["project_type"] == "gitlab":
            await webhook_manager.remove_gitlab_webhooks(
                project_id=subscription["project_id"],
                webhook_ids=subscription["webhook_ids"],
                access_token=subscription.get("access_token")
            )
        elif subscription["project_type"] == "sonarqube":
            await webhook_manager.remove_sonarqube_webhooks(
                project_key=subscription["project_id"],
                webhook_ids=subscription["webhook_ids"],
                access_token=subscription.get("access_token")
            )
        
        # Mark subscription as deleted
        await db.update_subscription(subscription_id, {"status": "deleted"})
        
        log.info(f"Deleted subscription {subscription_id}")
        return {"message": "Subscription deleted successfully"}
        
    except Exception as e:
        log.error(f"Failed to delete subscription: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{subscription_id}/refresh")
async def refresh_subscription(
    subscription_id: str,
    api_key: str = Depends(get_api_key)
):
    """Refresh subscription expiry and webhook configuration"""
    try:
        subscription = await db.get_subscription(subscription_id)
        
        if not subscription:
            raise HTTPException(status_code=404, detail="Subscription not found")
        
        # Verify ownership
        if subscription.get("api_key") != api_key:
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Extend expiry
        new_expiry = datetime.utcnow() + timedelta(days=settings.subscription_ttl_days)
        
        # Verify webhooks are still configured
        if subscription["project_type"] == "gitlab":
            active = await webhook_manager.verify_gitlab_webhooks(
                project_id=subscription["project_id"],
                webhook_ids=subscription["webhook_ids"],
                access_token=subscription.get("access_token")
            )
        else:
            active = await webhook_manager.verify_sonarqube_webhooks(
                project_key=subscription["project_id"],
                webhook_ids=subscription["webhook_ids"],
                access_token=subscription.get("access_token")
            )
        
        # Update subscription
        await db.update_subscription(subscription_id, {
            "expires_at": new_expiry,
            "status": "active" if active else "inactive",
            "last_refreshed": datetime.utcnow()
        })
        
        return {
            "subscription_id": subscription_id,
            "expires_at": new_expiry,
            "webhooks_active": active
        }
        
    except Exception as e:
        log.error(f"Failed to refresh subscription: {e}")
        raise HTTPException(status_code=500, detail=str(e))