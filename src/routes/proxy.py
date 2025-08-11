from flask import Blueprint, request, jsonify
from src.models.wishlist import db, Wishlist, WishlistSettings
from src.utils.shopify_api import ShopifyAPI  # if you use it elsewhere
import hmac
import hashlib
import urllib.parse

proxy_bp = Blueprint('proxy', __name__)

def verify_proxy_request(params):
    """
    TEMP verification so we can complete integration.
    (Shopify App Proxy always includes ?shop=...; once stable,
    replace with proper HMAC verification.)
    """
    return 'shop' in params

@proxy_bp.route('/proxy/wishlist.js', methods=['GET'])
def wishlist_js():
    """Serve the wishlist JavaScript widget"""

    if not verify_proxy_request(request.args):
        return "Unauthorized", 401

    shop = request.args.get('shop', '')

    # JavaScript widget (served from the proxy)
    js_code = f"""
(function() {{
  // --- Config -------------------------------------------------------
  var PRE = (window.WISHLIST_CONFIG || {});
  var WISHLIST_CONFIG = {{
    shop: PRE.shop || '{shop}',
    // IMPORTANT: Storefront calls /apps/wishlist/* (Shopify forwards to /proxy/* here)
    apiEndpoint: PRE.apiEndpoint || '/apps/wishlist',
    customerId: PRE.customerId || ((window.Shopify && window.Shopify.customer) ? window.Shopify.customer.id : null),
    isLoggedIn: PRE.isLoggedIn || !!(window.Shopify && window.Shopify.customer)
  }};

  // Init
  if (document.readyState === 'loading') {{
    document.addEventListener('DOMContentLoaded', initWishlist);
  }} else {{
    initWishlist();
  }}

  function initWishlist() {{
    // pick up customer from theme bootstrapping
    if (window.Shopify && window.Shopify.customer) {{
      WISHLIST_CONFIG.customerId = window.Shopify.customer.id;
      WISHLIST_CONFIG.isLoggedIn = true;
    }}

    // Inject buttons on PDP only (avoid duplicates)
    addWishlistButtons();

    // Update header counter
    updateWishlistCount();
  }}

  function addWishlistButtons() {{
    // Only forms that actually submit to /cart/add (avoid duplicates in Dawn)
    var productForms = document.querySelectorAll('form[action*="/cart/add"]');

    productForms.forEach(function(form) {{
      var productId = getProductId(form);
      if (productId && !form.querySelector('.wishlist-btn')) {{
        var wishlistBtn = createWishlistButton(productId);
        insertWishlistButton(form, wishlistBtn);
      }}
    }});
  }}

  function getProductId(el) {{
    // variant id input often named "id"
    var idInput = el.querySelector('input[name="id"]');
    if (idInput && idInput.value) return idInput.value;

    // Common data attributes sometimes used in cards/templates
    var pid = el.getAttribute('data-product-id') || el.getAttribute('data-id');
    if (pid) return pid;

    // Fallback (rare): parse from product link (handle) – not ideal for ID, so skip
    return null;
  }}

  function createWishlistButton(productId) {{
    var button = document.createElement('button');
    button.className = 'wishlist-btn';
    button.setAttribute('data-product-id', productId);
    button.textContent = '♡ Add to Wishlist';
    button.style.cssText = 'background:none;border:1px solid #ccc;padding:8px 12px;cursor:pointer;margin:5px 0;border-radius:4px;font-size:14px;';

    button.addEventListener('click', function(e) {{
      e.preventDefault();
      toggleWishlist(productId, button);
    }});

    // Pre-check
    checkWishlistStatus(productId, button);

    return button;
  }}

  function insertWishlistButton(container, button) {{
    var addToCartBtn = container.querySelector('button[type="submit"], .btn-cart, .add-to-cart');
    if (addToCartBtn && addToCartBtn.parentNode) {{
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
    var method = isInWishlist ? 'DELETE' : 'POST';
    var url = WISHLIST_CONFIG.apiEndpoint + '/wishlist';

    button.disabled = true;
    button.textContent = isInWishlist ? 'Removing...' : 'Adding...';

    var payload = {{
      customer_id: WISHLIST_CONFIG.customerId,
      shop_domain: WISHLIST_CONFIG.shop,
      variant_id: String(productId)
    }};

    fetch(url, {{
      method: method,
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify(payload)
    }})
    .then(function(r) {{ return r.json(); }})
    .then(function(data) {{
      if (data && data.success) {{
        updateButtonState(button, !isInWishlist);
        updateWishlistCount();
      }} else {{
        alert('Error: ' + (data && data.error || 'Unknown error'));
      }}
    }})
    .catch(function(err) {{
      console.error('Wishlist error:', err);
      alert('Error updating wishlist');
    }})
    .finally(function() {{
      button.disabled = false;
    }});
  }}

  function checkWishlistStatus(productId, button) {{
    if (!WISHLIST_CONFIG.isLoggedIn) return;

    var url = WISHLIST_CONFIG.apiEndpoint + '/wishlist'
            + '?customer_id=' + encodeURIComponent(WISHLIST_CONFIG.customerId)
            + '&shop_domain=' + encodeURIComponent(WISHLIST_CONFIG.shop);

    fetch(url)
      .then(function(r) {{ return r.json(); }})
      .then(function(data) {{
        if (data && data.success) {{
          var inList = (data.wishlist || []).some(function(item) {{
            return String(item.product_id) === String(productId);
          }});
          updateButtonState(button, inList);
        }}
      }})
      .catch(function(err) {{
        console.error('Error checking wishlist status:', err);
      }});
  }}

  function updateButtonState(button, isInWishlist) {{
    if (isInWishlist) {{
      button.classList.add('in-wishlist');
      button.textContent = '♥ In Wishlist';
      button.style.backgroundColor = '#ff6b6b';
      button.style.color = '#fff';
      button.style.borderColor = '#ff6b6b';
    }} else {{
      button.classList.remove('in-wishlist');
      button.textContent = '♡ Add to Wishlist';
      button.style.backgroundColor = 'transparent';
      button.style.color = '#333';
      button.style.borderColor = '#ccc';
    }}
  }}

  function updateWishlistCount() {{
    if (!WISHLIST_CONFIG.isLoggedIn) return;

    var url = WISHLIST_CONFIG.apiEndpoint + '/wishlist/count'
            + '?customer_id=' + encodeURIComponent(WISHLIST_CONFIG.customerId)
            + '&shop_domain=' + encodeURIComponent(WISHLIST_CONFIG.shop);

    fetch(url)
      .then(function(r) {{ return r.json(); }})
      .then(function(data) {{
        if (data && data.success) {{
          document.querySelectorAll('.wishlist-count').forEach(function(el) {{
            el.textContent = data.count;
          }});
        }}
      }})
      .catch(function(err) {{
        console.error('Error updating wishlist count:', err);
      }});
  }}

  // Expose a tiny API if you need it
  window.WishlistWidget = {{
    updateCount: updateWishlistCount,
    refreshButtons: addWishlistButtons
  }};
}})();
"""
    return js_code, 200, {'Content-Type': 'application/javascript'}


@proxy_bp.route('/proxy/wishlist', methods=['GET', 'POST', 'DELETE'])
def proxy_wishlist():
    """Proxy endpoint for wishlist operations (Shopify forwards /apps/wishlist/* here)"""

    if not verify_proxy_request(request.args):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    shop = request.args.get('shop')
    if not shop:
        return jsonify({'success': False, 'error': 'Missing shop'}), 400

    # Ensure the shop is configured
    shop_settings = WishlistSettings.query.filter_by(shop_domain=shop).first()
    if not shop_settings:
        return jsonify({'success': False, 'error': 'Shop not configured'}), 400

    try:
        if request.method == 'GET':
            return get_wishlist_proxy(shop)
        elif request.method == 'POST':
            return add_to_wishlist_proxy(shop)
        elif request.method == 'DELETE':
            return remove_from_wishlist_proxy(shop)
    except Exception as e:
        # Catch any unexpected exception so the client always gets JSON
        return jsonify({'success': False, 'error': f'unhandled: {str(e)}'}), 500


def get_wishlist_proxy(shop):
    """Get wishlist items via proxy"""
    customer_id = request.args.get('customer_id')
    if not customer_id:
        return jsonify({'success': False, 'error': 'customer_id is required'}), 400

    try:
        items = Wishlist.query.filter_by(
            customer_id=str(customer_id),
            shop_domain=shop
        ).all()

        return jsonify({
            'success': True,
            'wishlist': [i.to_dict() for i in items]
        })
    except Exception as e:
        return jsonify({'success': False, 'error': f'get_failed: {str(e)}'}), 500


def add_to_wishlist_proxy(shop):
    """Add item to wishlist via proxy"""
    data = request.get_json(silent=True) or request.form or {}
    customer_id = data.get('customer_id')
    product_id  = data.get('product_id')
    variant_id  = data.get('variant_id')

    # Require customer_id and at least one of product_id or variant_id
    if not customer_id or not (product_id or variant_id):
        return jsonify({'success': False, 'error': 'customer_id and product_id or variant_id are required'}), 400

    try:
        existing = Wishlist.query.filter_by(
            customer_id=str(customer_id),
            shop_domain=shop,
            product_id=str(product_id) if product_id else None,
            variant_id=str(variant_id) if variant_id else None
        ).first()

        if existing:
            return jsonify({'success': False, 'error': 'Item already in wishlist'}), 409

        item = Wishlist(
            customer_id=str(customer_id),
            shop_domain=shop,
            product_id=str(product_id) if product_id else None,
            variant_id=str(variant_id) if variant_id else None
        )
        db.session.add(item)
        db.session.commit()

        return jsonify({'success': True, 'message': 'Item added to wishlist'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'add_failed: {str(e)}'}), 500


def remove_from_wishlist_proxy(shop):
    """Remove item from wishlist via proxy"""
    data = request.get_json(silent=True) or request.form or {}
    customer_id = data.get('customer_id')
    product_id  = data.get('product_id')
    variant_id  = data.get('variant_id')

    # Require customer_id and at least one of product_id or variant_id
    if not customer_id or not (product_id or variant_id):
        return jsonify({'success': False, 'error': 'customer_id and product_id or variant_id are required'}), 400

    try:
        q = Wishlist.query.filter_by(
            customer_id=str(customer_id),
            shop_domain=shop
        )
        if product_id:
            q = q.filter_by(product_id=str(product_id))
        if variant_id:
            q = q.filter_by(variant_id=str(variant_id))

        item = q.first()

        if not item:
            return jsonify({'success': False, 'error': 'Item not found'}), 404

        db.session.delete(item)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Item removed from wishlist'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'remove_failed: {str(e)}'}), 500


@proxy_bp.route('/proxy/wishlist/count', methods=['GET'])
def proxy_wishlist_count():
    """Get wishlist count via proxy"""
    if not verify_proxy_request(request.args):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    shop = request.args.get('shop')
    customer_id = request.args.get('customer_id')

    if not shop or not customer_id:
        return jsonify({'success': False, 'error': 'shop and customer_id are required'}), 400

    try:
        count = Wishlist.query.filter_by(
            customer_id=str(customer_id),
            shop_domain=shop
        ).count()
        return jsonify({'success': True, 'count': count})
    except Exception as e:
        return jsonify({'success': False, 'error': f'count_failed: {str(e)}'}), 500


@proxy_bp.route('/proxy', methods=['GET'])
def shopify_proxy_root():
    return jsonify({"success": True, "wishlist": []})
