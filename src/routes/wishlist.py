from flask import Blueprint, request, jsonify
from src.models.wishlist import db, Wishlist, WishlistSettings
from src.utils.shopify_api import ShopifyAPI
import json

wishlist_bp = Blueprint('wishlist', __name__)

@wishlist_bp.route('/wishlist', methods=['GET'])
def get_wishlist():
    """Get wishlist items for a customer"""
    customer_id = request.args.get('customer_id')
    shop_domain = request.args.get('shop_domain')
    
    if not customer_id or not shop_domain:
        return jsonify({'error': 'customer_id and shop_domain are required'}), 400
    
    try:
        # Get wishlist items from database
        wishlist_items = Wishlist.query.filter_by(
            customer_id=customer_id,
            shop_domain=shop_domain
        ).all()
        
        # Get shop settings for API access
        shop_settings = WishlistSettings.query.filter_by(shop_domain=shop_domain).first()
        if not shop_settings:
            return jsonify({'error': 'Shop not configured'}), 400
        
        # Initialize Shopify API
        shopify_api = ShopifyAPI(shop_domain, shop_settings.access_token)
        
        # Enrich wishlist items with product data
        enriched_items = []
        for item in wishlist_items:
            try:
                product_data = shopify_api.get_product(item.product_id)
                if product_data:
                    enriched_item = item.to_dict()
                    enriched_item['product'] = product_data
                    enriched_items.append(enriched_item)
            except Exception as e:
                print(f"Error fetching product {item.product_id}: {e}")
                # Include item even if product fetch fails
                enriched_items.append(item.to_dict())
        
        return jsonify({
            'success': True,
            'wishlist': enriched_items
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@wishlist_bp.route('/wishlist', methods=['POST'])
def add_to_wishlist():
    """Add item to wishlist"""
    data = request.get_json()
    
    required_fields = ['customer_id', 'shop_domain', 'product_id']
    for field in required_fields:
        if not data.get(field):
            return jsonify({'error': f'{field} is required'}), 400
    
    try:
        # Check if item already exists
        existing_item = Wishlist.query.filter_by(
            customer_id=data['customer_id'],
            shop_domain=data['shop_domain'],
            product_id=data['product_id'],
            variant_id=data.get('variant_id')
        ).first()
        
        if existing_item:
            return jsonify({'error': 'Item already in wishlist'}), 409
        
        # Create new wishlist item
        wishlist_item = Wishlist(
            customer_id=data['customer_id'],
            shop_domain=data['shop_domain'],
            product_id=data['product_id'],
            variant_id=data.get('variant_id')
        )
        
        db.session.add(wishlist_item)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Item added to wishlist',
            'item': wishlist_item.to_dict()
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@wishlist_bp.route('/wishlist/<int:item_id>', methods=['DELETE'])
def remove_from_wishlist(item_id):
    """Remove item from wishlist"""
    customer_id = request.args.get('customer_id')
    shop_domain = request.args.get('shop_domain')
    
    if not customer_id or not shop_domain:
        return jsonify({'error': 'customer_id and shop_domain are required'}), 400
    
    try:
        # Find and delete the item
        wishlist_item = Wishlist.query.filter_by(
            id=item_id,
            customer_id=customer_id,
            shop_domain=shop_domain
        ).first()
        
        if not wishlist_item:
            return jsonify({'error': 'Item not found'}), 404
        
        db.session.delete(wishlist_item)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Item removed from wishlist'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@wishlist_bp.route('/wishlist/clear', methods=['DELETE'])
def clear_wishlist():
    """Clear all items from wishlist"""
    customer_id = request.args.get('customer_id')
    shop_domain = request.args.get('shop_domain')
    
    if not customer_id or not shop_domain:
        return jsonify({'error': 'customer_id and shop_domain are required'}), 400
    
    try:
        # Delete all items for the customer
        deleted_count = Wishlist.query.filter_by(
            customer_id=customer_id,
            shop_domain=shop_domain
        ).delete()
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Cleared {deleted_count} items from wishlist'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@wishlist_bp.route('/wishlist/count', methods=['GET'])
def get_wishlist_count():
    """Get count of items in wishlist"""
    customer_id = request.args.get('customer_id')
    shop_domain = request.args.get('shop_domain')
    
    if not customer_id or not shop_domain:
        return jsonify({'error': 'customer_id and shop_domain are required'}), 400
    
    try:
        count = Wishlist.query.filter_by(
            customer_id=customer_id,
            shop_domain=shop_domain
        ).count()
        
        return jsonify({
            'success': True,
            'count': count
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

