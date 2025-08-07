from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import json

db = SQLAlchemy()

class Wishlist(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.String(255), nullable=False)  # Shopify customer ID
    shop_domain = db.Column(db.String(255), nullable=False)  # Store domain
    product_id = db.Column(db.String(255), nullable=False)   # Shopify product ID
    variant_id = db.Column(db.String(255), nullable=True)    # Shopify variant ID (optional)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Composite unique constraint to prevent duplicate entries
    __table_args__ = (db.UniqueConstraint('customer_id', 'shop_domain', 'product_id', 'variant_id', name='unique_wishlist_item'),)

    def __repr__(self):
        return f'<Wishlist customer_id={self.customer_id} product_id={self.product_id}>'

    def to_dict(self):
        return {
            'id': self.id,
            'customer_id': self.customer_id,
            'shop_domain': self.shop_domain,
            'product_id': self.product_id,
            'variant_id': self.variant_id,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class WishlistSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    shop_domain = db.Column(db.String(255), unique=True, nullable=False)
    access_token = db.Column(db.String(255), nullable=False)  # Shopify access token
    webhook_secret = db.Column(db.String(255), nullable=True)  # For webhook verification
    settings = db.Column(db.Text, nullable=True)  # JSON string for app settings
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<WishlistSettings shop_domain={self.shop_domain}>'

    def to_dict(self):
        return {
            'id': self.id,
            'shop_domain': self.shop_domain,
            'settings': json.loads(self.settings) if self.settings else {},
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

    def get_settings(self):
        return json.loads(self.settings) if self.settings else {}

    def set_settings(self, settings_dict):
        self.settings = json.dumps(settings_dict)

