from flask import Blueprint, request, jsonify, redirect, session
from src.models.wishlist import db, WishlistSettings
from src.utils.shopify_auth import ShopifyAuth
import os

auth_bp = Blueprint('auth', __name__)

# Shopify app credentials (should be set as environment variables)
SHOPIFY_API_KEY = os.getenv('SHOPIFY_API_KEY', 'your_api_key_here')
SHOPIFY_API_SECRET = os.getenv('SHOPIFY_API_SECRET', 'your_api_secret_here')
SHOPIFY_SCOPES = 'read_products,read_customers,write_customers'
SHOPIFY_REDIRECT_URI = os.getenv('SHOPIFY_REDIRECT_URI', 'http://localhost:5000/api/auth/callback')

@auth_bp.route('/auth', methods=['GET'])
def auth():
    """Initiate Shopify OAuth flow"""
    shop = request.args.get('shop')
    
    if not shop:
        return jsonify({'error': 'shop parameter is required'}), 400
    
    # Ensure shop domain format
    if not shop.endswith('.myshopify.com'):
        shop = f"{shop}.myshopify.com"
    
    try:
        shopify_auth = ShopifyAuth(SHOPIFY_API_KEY, SHOPIFY_API_SECRET)
        auth_url = shopify_auth.get_auth_url(shop, SHOPIFY_SCOPES, SHOPIFY_REDIRECT_URI)
        
        # Store shop in session for callback
        session['shop'] = shop
        
        return redirect(auth_url)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@auth_bp.route('/auth/callback', methods=['GET'])
def auth_callback():
    """Handle Shopify OAuth callback"""
    shop = session.get('shop')
    code = request.args.get('code')
    hmac = request.args.get('hmac')
    
    if not shop or not code:
        return jsonify({'error': 'Invalid callback parameters'}), 400
    
    try:
        shopify_auth = ShopifyAuth(SHOPIFY_API_KEY, SHOPIFY_API_SECRET)
        
        # Verify the callback
        if not shopify_auth.verify_callback(request.args):
            return jsonify({'error': 'Invalid callback verification'}), 400
        
        # Exchange code for access token
        access_token = shopify_auth.get_access_token(shop, code)
        
        if not access_token:
            return jsonify({'error': 'Failed to get access token'}), 400
        
        # Store or update shop settings
        shop_settings = WishlistSettings.query.filter_by(shop_domain=shop).first()
        
        if shop_settings:
            shop_settings.access_token = access_token
        else:
            shop_settings = WishlistSettings(
                shop_domain=shop,
                access_token=access_token
            )
            db.session.add(shop_settings)
        
        db.session.commit()
        
        # Clear session
        session.pop('shop', None)
        
        return jsonify({
            'success': True,
            'message': 'App installed successfully',
            'shop': shop
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@auth_bp.route('/auth/verify', methods=['GET'])
def verify_installation():
    """Verify if app is installed for a shop"""
    shop = request.args.get('shop')
    
    if not shop:
        return jsonify({'error': 'shop parameter is required'}), 400
    
    # Ensure shop domain format
    if not shop.endswith('.myshopify.com'):
        shop = f"{shop}.myshopify.com"
    
    try:
        shop_settings = WishlistSettings.query.filter_by(shop_domain=shop).first()
        
        return jsonify({
            'installed': shop_settings is not None,
            'shop': shop
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@auth_bp.route('/auth/uninstall', methods=['POST'])
def uninstall():
    """Handle app uninstallation"""
    shop = request.args.get('shop')
    
    if not shop:
        return jsonify({'error': 'shop parameter is required'}), 400
    
    # Ensure shop domain format
    if not shop.endswith('.myshopify.com'):
        shop = f"{shop}.myshopify.com"
    
    try:
        # Remove shop settings
        shop_settings = WishlistSettings.query.filter_by(shop_domain=shop).first()
        if shop_settings:
            db.session.delete(shop_settings)
        
        # Remove all wishlist data for the shop
        Wishlist.query.filter_by(shop_domain=shop).delete()
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'App uninstalled successfully'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

