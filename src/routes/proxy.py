from flask import Blueprint, request, jsonify, render_template_string
from src.models.wishlist import db, Wishlist, WishlistSettings
from src.utils.shopify_api import ShopifyAPI
import hmac
import hashlib
import urllib.parse

proxy_bp = Blueprint('proxy', __name__)

def verify_proxy_request(params):
    """Verify that the request is coming from Shopify"""
    # This is a simplified verification - in production, you should implement proper HMAC verification
    required_params = ['shop', 'timestamp']
    return all(param in params for param in required_params)

@proxy_bp.route('/proxy/wishlist.js', methods=['GET'])
def wishlist_js():
    """Serve the wishlist JavaScript widget"""
    
    # Verify the request is from Shopify
    if not verify_proxy_request(request.args):
        return "Unauthorized", 401
    
    shop = request.args.get('shop')
    
    # JavaScript widget code
    js_code = f"""
(function() {{
    // Wishlist Widget Configuration
    var WISHLIST_CONFIG = {{
        shop: '{shop}',
        apiEndpoint: '/apps/wishlist/proxy',
        customerId: null,
        isLoggedIn: false
    }};
    
    // Initialize wishlist when DOM is ready
    if (document.readyState === 'loading') {{
        document.addEventListener('DOMContentLoaded', initWishlist);
    }} else {{
        initWishlist();
    }}
    
    function initWishlist() {{
        // Check if customer is logged in
        if (window.Shopify && window.Shopify.customer) {{
            WISHLIST_CONFIG.customerId = window.Shopify.customer.id;
            WISHLIST_CONFIG.isLoggedIn = true;
        }}
        
        // Add wishlist buttons to products
        addWishlistButtons();
        
        // Load wishlist count
        updateWishlistCount();
    }}
    
    function addWishlistButtons() {{
        // Find product forms or product containers
        var productForms = document.querySelectorAll('form[action*="/cart/add"], .product-item, .product-card');
        
        productForms.forEach(function(form) {{
            var productId = getProductId(form);
            if (productId && !form.querySelector('.wishlist-btn')) {{
                var wishlistBtn = createWishlistButton(productId);
                insertWishlistButton(form, wishlistBtn);
            }}
        }});
    }}
    
    function getProductId(element) {{
        // Try to find product ID from various sources
        var productIdInput = element.querySelector('input[name="id"]');
        if (productIdInput) {{
            return productIdInput.value;
        }}
        
        // Try data attributes
        var productId = element.getAttribute('data-product-id') || 
                       element.getAttribute('data-id');
        if (productId) {{
            return productId;
        }}
        
        // Try to extract from URL or other sources
        var productLink = element.querySelector('a[href*="/products/"]');
        if (productLink) {{
            var match = productLink.href.match(/\\/products\\/([^?#\\/]+)/);
            if (match) {{
                // This would need to be converted to product ID via API
                return match[1];
            }}
        }}
        
        return null;
    }}
    
    function createWishlistButton(productId) {{
        var button = document.createElement('button');
        button.className = 'wishlist-btn';
        button.setAttribute('data-product-id', productId);
        button.innerHTML = '♡ Add to Wishlist';
        button.style.cssText = `
            background: none;
            border: 1px solid #ccc;
            padding: 8px 12px;
            cursor: pointer;
            margin: 5px 0;
            border-radius: 4px;
            font-size: 14px;
        `;
        
        button.addEventListener('click', function(e) {{
            e.preventDefault();
            toggleWishlist(productId, button);
        }});
        
        // Check if item is already in wishlist
        checkWishlistStatus(productId, button);
        
        return button;
    }}
    
    function insertWishlistButton(container, button) {{
        // Try to find the best place to insert the button
        var addToCartBtn = container.querySelector('button[type="submit"], .btn-cart, .add-to-cart');
        if (addToCartBtn) {{
            addToCartBtn.parentNode.insertBefore(button, addToCartBtn.nextSibling);
        }} else {{
            container.appendChild(button);
        }}
    }}
    
    function toggleWishlist(productId, button) {{
        if (!WISHLIST_CONFIG.isLoggedIn) {{
            alert('Please log in to use the wishlist feature.');
            return;
        }}
        
        var isInWishlist = button.classList.contains('in-wishlist');
        var action = isInWishlist ? 'remove' : 'add';
        
        button.disabled = true;
        button.innerHTML = action === 'add' ? 'Adding...' : 'Removing...';
        
        var url = WISHLIST_CONFIG.apiEndpoint + '/wishlist';
        var method = action === 'add' ? 'POST' : 'DELETE';
        
        var requestData = {{
            customer_id: WISHLIST_CONFIG.customerId,
            shop_domain: WISHLIST_CONFIG.shop,
            product_id: productId
        }};
        
        fetch(url, {{
            method: method,
            headers: {{
                'Content-Type': 'application/json',
            }},
            body: JSON.stringify(requestData)
        }})
        .then(response => response.json())
        .then(data => {{
            if (data.success) {{
                updateButtonState(button, !isInWishlist);
                updateWishlistCount();
            }} else {{
                alert('Error: ' + (data.error || 'Unknown error'));
            }}
        }})
        .catch(error => {{
            console.error('Wishlist error:', error);
            alert('Error updating wishlist');
        }})
        .finally(() => {{
            button.disabled = false;
        }});
    }}
    
    function checkWishlistStatus(productId, button) {{
        if (!WISHLIST_CONFIG.isLoggedIn) return;
        
        var url = WISHLIST_CONFIG.apiEndpoint + '/wishlist?' + 
                 'customer_id=' + WISHLIST_CONFIG.customerId + 
                 '&shop_domain=' + WISHLIST_CONFIG.shop;
        
        fetch(url)
        .then(response => response.json())
        .then(data => {{
            if (data.success) {{
                var isInWishlist = data.wishlist.some(item => item.product_id === productId);
                updateButtonState(button, isInWishlist);
            }}
        }})
        .catch(error => {{
            console.error('Error checking wishlist status:', error);
        }});
    }}
    
    function updateButtonState(button, isInWishlist) {{
        if (isInWishlist) {{
            button.classList.add('in-wishlist');
            button.innerHTML = '♥ In Wishlist';
            button.style.backgroundColor = '#ff6b6b';
            button.style.color = 'white';
            button.style.borderColor = '#ff6b6b';
        }} else {{
            button.classList.remove('in-wishlist');
            button.innerHTML = '♡ Add to Wishlist';
            button.style.backgroundColor = 'transparent';
            button.style.color = '#333';
            button.style.borderColor = '#ccc';
        }}
    }}
    
    function updateWishlistCount() {{
        if (!WISHLIST_CONFIG.isLoggedIn) return;
        
        var url = WISHLIST_CONFIG.apiEndpoint + '/wishlist/count?' + 
                 'customer_id=' + WISHLIST_CONFIG.customerId + 
                 '&shop_domain=' + WISHLIST_CONFIG.shop;
        
        fetch(url)
        .then(response => response.json())
        .then(data => {{
            if (data.success) {{
                // Update wishlist count in header or wherever it's displayed
                var countElements = document.querySelectorAll('.wishlist-count');
                countElements.forEach(function(element) {{
                    element.textContent = data.count;
                }});
            }}
        }})
        .catch(error => {{
            console.error('Error updating wishlist count:', error);
        }});
    }}
    
    // Expose functions globally for manual use
    window.WishlistWidget = {{
        addToWishlist: function(productId) {{
            var button = document.querySelector('[data-product-id="' + productId + '"]');
            if (button) {{
                toggleWishlist(productId, button);
            }}
        }},
        removeFromWishlist: function(productId) {{
            var button = document.querySelector('[data-product-id="' + productId + '"]');
            if (button && button.classList.contains('in-wishlist')) {{
                toggleWishlist(productId, button);
            }}
        }},
        refreshButtons: addWishlistButtons,
        updateCount: updateWishlistCount
    }};
}})();
"""
    
    return js_code, 200, {'Content-Type': 'application/javascript'}

@proxy_bp.route('/proxy/wishlist', methods=['GET', 'POST', 'DELETE'])
def proxy_wishlist():
    """Proxy endpoint for wishlist operations"""
    
    # Verify the request is from Shopify
    if not verify_proxy_request(request.args):
        return jsonify({'error': 'Unauthorized'}), 401
    
    shop = request.args.get('shop')
    
    # Get shop settings
    shop_settings = WishlistSettings.query.filter_by(shop_domain=shop).first()
    if not shop_settings:
        return jsonify({'error': 'Shop not configured'}), 400
    
    if request.method == 'GET':
        return get_wishlist_proxy(shop)
    elif request.method == 'POST':
        return add_to_wishlist_proxy(shop)
    elif request.method == 'DELETE':
        return remove_from_wishlist_proxy(shop)

def get_wishlist_proxy(shop):
    """Get wishlist items via proxy"""
    customer_id = request.args.get('customer_id')
    
    if not customer_id:
        return jsonify({'error': 'customer_id is required'}), 400
    
    try:
        wishlist_items = Wishlist.query.filter_by(
            customer_id=customer_id,
            shop_domain=shop
        ).all()
        
        return jsonify({
            'success': True,
            'wishlist': [item.to_dict() for item in wishlist_items]
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def add_to_wishlist_proxy(shop):
    """Add item to wishlist via proxy"""
    data = request.get_json()
    
    if not data or not data.get('customer_id') or not data.get('product_id'):
        return jsonify({'error': 'customer_id and product_id are required'}), 400
    
    try:
        # Check if item already exists
        existing_item = Wishlist.query.filter_by(
            customer_id=data['customer_id'],
            shop_domain=shop,
            product_id=data['product_id'],
            variant_id=data.get('variant_id')
        ).first()
        
        if existing_item:
            return jsonify({'error': 'Item already in wishlist'}), 409
        
        # Create new wishlist item
        wishlist_item = Wishlist(
            customer_id=data['customer_id'],
            shop_domain=shop,
            product_id=data['product_id'],
            variant_id=data.get('variant_id')
        )
        
        db.session.add(wishlist_item)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Item added to wishlist'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

def remove_from_wishlist_proxy(shop):
    """Remove item from wishlist via proxy"""
    data = request.get_json()
    
    if not data or not data.get('customer_id') or not data.get('product_id'):
        return jsonify({'error': 'customer_id and product_id are required'}), 400
    
    try:
        # Find and delete the item
        wishlist_item = Wishlist.query.filter_by(
            customer_id=data['customer_id'],
            shop_domain=shop,
            product_id=data['product_id'],
            variant_id=data.get('variant_id')
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

@proxy_bp.route('/proxy/wishlist/count', methods=['GET'])
def proxy_wishlist_count():
    """Get wishlist count via proxy"""
    
    # Verify the request is from Shopify
    if not verify_proxy_request(request.args):
        return jsonify({'error': 'Unauthorized'}), 401
    
    shop = request.args.get('shop')
    customer_id = request.args.get('customer_id')
    
    if not customer_id:
        return jsonify({'error': 'customer_id is required'}), 400
    
    try:
        count = Wishlist.query.filter_by(
            customer_id=customer_id,
            shop_domain=shop
        ).count()
        
        return jsonify({
            'success': True,
            'count': count
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@proxy_bp.route('/proxy', methods=['GET'])
def shopify_proxy_root():
    return jsonify({"wishlist": []})