import requests
import json
from typing import Optional, Dict, Any

class ShopifyAPI:
    """Utility class for interacting with Shopify Admin API"""
    
    def __init__(self, shop_domain: str, access_token: str):
        self.shop_domain = shop_domain
        self.access_token = access_token
        self.base_url = f"https://{shop_domain}/admin/api/2023-10"
        self.headers = {
            'X-Shopify-Access-Token': access_token,
            'Content-Type': 'application/json'
        }
    
    def _make_request(self, method: str, endpoint: str, data: Optional[Dict] = None) -> Optional[Dict]:
        """Make a request to Shopify API"""
        url = f"{self.base_url}/{endpoint}"
        
        try:
            if method.upper() == 'GET':
                response = requests.get(url, headers=self.headers)
            elif method.upper() == 'POST':
                response = requests.post(url, headers=self.headers, json=data)
            elif method.upper() == 'PUT':
                response = requests.put(url, headers=self.headers, json=data)
            elif method.upper() == 'DELETE':
                response = requests.delete(url, headers=self.headers)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            
            response.raise_for_status()
            
            if response.content:
                return response.json()
            return {}
            
        except requests.exceptions.RequestException as e:
            print(f"Shopify API request failed: {e}")
            return None
    
    def get_product(self, product_id: str) -> Optional[Dict]:
        """Get product details by ID"""
        response = self._make_request('GET', f"products/{product_id}.json")
        return response.get('product') if response else None
    
    def get_products(self, limit: int = 50, page_info: Optional[str] = None) -> Optional[Dict]:
        """Get list of products"""
        endpoint = f"products.json?limit={limit}"
        if page_info:
            endpoint += f"&page_info={page_info}"
        
        response = self._make_request('GET', endpoint)
        return response if response else None
    
    def get_customer(self, customer_id: str) -> Optional[Dict]:
        """Get customer details by ID"""
        response = self._make_request('GET', f"customers/{customer_id}.json")
        return response.get('customer') if response else None
    
    def get_customer_metafields(self, customer_id: str) -> Optional[list]:
        """Get customer metafields"""
        response = self._make_request('GET', f"customers/{customer_id}/metafields.json")
        return response.get('metafields') if response else None
    
    def create_customer_metafield(self, customer_id: str, namespace: str, key: str, value: Any, value_type: str = 'json') -> Optional[Dict]:
        """Create a customer metafield"""
        data = {
            'metafield': {
                'namespace': namespace,
                'key': key,
                'value': json.dumps(value) if value_type == 'json' else str(value),
                'type': value_type
            }
        }
        
        response = self._make_request('POST', f"customers/{customer_id}/metafields.json", data)
        return response.get('metafield') if response else None
    
    def update_customer_metafield(self, customer_id: str, metafield_id: str, value: Any, value_type: str = 'json') -> Optional[Dict]:
        """Update a customer metafield"""
        data = {
            'metafield': {
                'id': metafield_id,
                'value': json.dumps(value) if value_type == 'json' else str(value),
                'type': value_type
            }
        }
        
        response = self._make_request('PUT', f"customers/{customer_id}/metafields/{metafield_id}.json", data)
        return response.get('metafield') if response else None
    
    def delete_customer_metafield(self, customer_id: str, metafield_id: str) -> bool:
        """Delete a customer metafield"""
        response = self._make_request('DELETE', f"customers/{customer_id}/metafields/{metafield_id}.json")
        return response is not None
    
    def get_product_variants(self, product_id: str) -> Optional[list]:
        """Get product variants"""
        response = self._make_request('GET', f"products/{product_id}/variants.json")
        return response.get('variants') if response else None
    
    def get_variant(self, variant_id: str) -> Optional[Dict]:
        """Get variant details by ID"""
        response = self._make_request('GET', f"variants/{variant_id}.json")
        return response.get('variant') if response else None
    
    def search_products(self, query: str, limit: int = 50) -> Optional[Dict]:
        """Search products"""
        endpoint = f"products.json?limit={limit}&title={query}"
        response = self._make_request('GET', endpoint)
        return response if response else None
    
    def get_shop_info(self) -> Optional[Dict]:
        """Get shop information"""
        response = self._make_request('GET', "shop.json")
        return response.get('shop') if response else None

