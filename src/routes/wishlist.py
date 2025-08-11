from flask import Blueprint, request, jsonify
from src.models.wishlist import db, Wishlist, WishlistSettings
from src.utils.shopify_api import ShopifyAPI

wishlist_bp = Blueprint('wishlist', __name__)

# ---------------------------- helpers ----------------------------

def _json_ok(payload: dict, status: int = 200):
    payload.setdefault('success', True)
    return jsonify(payload), status

def _json_err(message: str, status: int = 400):
    return jsonify({'success': False, 'error': message}), status

def _shop_from_request():
    """
    Prefer explicit shop_domain param, but accept Shopify proxy header or ?shop=...
    """
    return (
        request.args.get('shop_domain')
        or request.args.get('shop')
        or request.headers.get('X-Shopify-Shop-Domain')
    )

def _body():
    # Accept JSON or form body
    return (request.get_json(silent=True) or request.form or {})

def _require_shop_and_customer():
    shop_domain = _shop_from_request()
    customer_id = request.args.get('customer_id') or _body().get('customer_id')
    if not customer_id or not shop_domain:
        return None, None, _json_err('customer_id and shop_domain are required', 400)
    return str(customer_id), str(shop_domain), None

# ---------------------------- routes ----------------------------

@wishlist_bp.route('/wishlist', methods=['GET'])
def get_wishlist():
    """Get wishlist items for a customer (optionally enriched with product data)."""
    customer_id, shop_domain, err = _require_shop_and_customer()
    if err:
        return err

    try:
        items = Wishlist.query.filter_by(
            customer_id=customer_id,
            shop_domain=shop_domain
        ).all()

        # Optional: enrich with product info if the shop is configured
        enriched = []
        shop_settings = WishlistSettings.query.filter_by(shop_domain=shop_domain).first()
        shopify_api = None
        if shop_settings:
            shopify_api = ShopifyAPI(shop_domain, shop_settings.access_token)

        for it in items:
            row = it.to_dict()
            if shopify_api and it.product_id:
                try:
                    product = shopify_api.get_product(it.product_id)
                    if product:
                        row['product'] = product
                except Exception as e:
                    # Keep item even if enrichment fails
                    # (do not raise; just return the basic row)
                    row['product_error'] = str(e)
            enriched.append(row)

        return _json_ok({'wishlist': enriched})
    except Exception as e:
        return _json_err(f'get_failed: {str(e)}', 500)


@wishlist_bp.route('/wishlist', methods=['POST'])
def add_to_wishlist():
    """Add item to wishlist (accepts product_id OR variant_id)."""
    data = _body()
    customer_id, shop_domain, err = _require_shop_and_customer()
    if err:
        return err

    product_id = data.get('product_id')
    variant_id = data.get('variant_id')

    if not (product_id or variant_id):
        return _json_err('product_id or variant_id is required', 400)

    try:
        existing = Wishlist.query.filter_by(
            customer_id=str(customer_id),
            shop_domain=str(shop_domain),
            product_id=str(product_id) if product_id else None,
            variant_id=str(variant_id) if variant_id else None
        ).first()

        if existing:
            return _json_err('Item already in wishlist', 409)

        item = Wishlist(
            customer_id=str(customer_id),
            shop_domain=str(shop_domain),
            product_id=str(product_id) if product_id else None,
            variant_id=str(variant_id) if variant_id else None
        )
        db.session.add(item)
        db.session.commit()

        return _json_ok({'message': 'Item added to wishlist', 'item': item.to_dict()}, 201)
    except Exception as e:
        db.session.rollback()
        return _json_err(f'add_failed: {str(e)}', 500)


@wishlist_bp.route('/wishlist', methods=['DELETE'])
def remove_from_wishlist_by_body():
    """
    Remove by product_id or variant_id (used by PDP toggle).
    Body: { customer_id, shop_domain, product_id? or variant_id? }
    """
    data = _body()
    customer_id, shop_domain, err = _require_shop_and_customer()
    if err:
        return err

    product_id = data.get('product_id')
    variant_id = data.get('variant_id')
    if not (product_id or variant_id):
        return _json_err('product_id or variant_id is required', 400)

    try:
        q = Wishlist.query.filter_by(
            customer_id=str(customer_id),
            shop_domain=str(shop_domain)
        )
        if product_id:
            q = q.filter_by(product_id=str(product_id))
        if variant_id:
            q = q.filter_by(variant_id=str(variant_id))

        item = q.first()
        if not item:
            return _json_err('Item not found', 404)

        db.session.delete(item)
        db.session.commit()
        return _json_ok({'message': 'Item removed from wishlist'})
    except Exception as e:
        db.session.rollback()
        return _json_err(f'remove_failed: {str(e)}', 500)


@wishlist_bp.route('/wishlist/<int:item_id>', methods=['DELETE'])
def remove_from_wishlist(item_id: int):
    """
    Remove by wishlist row id (used on the wishlist page itself).
    Query: ?customer_id=..&shop_domain=..
    """
    customer_id, shop_domain, err = _require_shop_and_customer()
    if err:
        return err

    try:
        item = Wishlist.query.filter_by(
            id=item_id,
            customer_id=str(customer_id),
            shop_domain=str(shop_domain)
        ).first()

        if not item:
            return _json_err('Item not found', 404)

        db.session.delete(item)
        db.session.commit()
        return _json_ok({'message': 'Item removed from wishlist'})
    except Exception as e:
        db.session.rollback()
        return _json_err(f'remove_failed: {str(e)}', 500)


@wishlist_bp.route('/wishlist/clear', methods=['DELETE'])
def clear_wishlist():
    """Clear all items from a customer's wishlist."""
    customer_id, shop_domain, err = _require_shop_and_customer()
    if err:
        return err

    try:
        deleted = Wishlist.query.filter_by(
            customer_id=str(customer_id),
            shop_domain=str(shop_domain)
        ).delete()
        db.session.commit()
        return _json_ok({'message': f'Cleared {deleted} items from wishlist'})
    except Exception as e:
        db.session.rollback()
        return _json_err(f'clear_failed: {str(e)}', 500)


@wishlist_bp.route('/wishlist/count', methods=['GET'])
def get_wishlist_count():
    """Get count of wishlist items for a customer."""
    customer_id, shop_domain, err = _require_shop_and_customer()
    if err:
        return err

    try:
        count = Wishlist.query.filter_by(
            customer_id=str(customer_id),
            shop_domain=str(shop_domain)
        ).count()
        return _json_ok({'count': count})
    except Exception as e:
        return _json_err(f'count_failed: {str(e)}', 500)
