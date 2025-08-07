import requests
import hmac
import hashlib
import urllib.parse
from typing import Optional, Dict

class ShopifyAuth:
    """Utility class for handling Shopify OAuth authentication"""
    
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
    
    def get_auth_url(self, shop: str, scopes: str, redirect_uri: str, state: Optional[str] = None) -> str:
        """Generate Shopify OAuth authorization URL"""
        params = {
            'client_id': self.api_key,
            'scope': scopes,
            'redirect_uri': redirect_uri,
            'state': state or '',
        }
        
        query_string = urllib.parse.urlencode(params)
        return f"https://{shop}/admin/oauth/authorize?{query_string}"
    
    def verify_callback(self, params: Dict) -> bool:
        """Verify the authenticity of the callback from Shopify"""
        if 'hmac' not in params:
            return False
        
        # Get the HMAC from params
        received_hmac = params.get('hmac')
        
        # Create a copy of params without the HMAC
        params_copy = dict(params)
        params_copy.pop('hmac', None)
        
        # Sort parameters and create query string
        sorted_params = sorted(params_copy.items())
        query_string = urllib.parse.urlencode(sorted_params)
        
        # Calculate expected HMAC
        expected_hmac = hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        # Compare HMACs
        return hmac.compare_digest(received_hmac, expected_hmac)
    
    def get_access_token(self, shop: str, code: str) -> Optional[str]:
        """Exchange authorization code for access token"""
        url = f"https://{shop}/admin/oauth/access_token"
        
        data = {
            'client_id': self.api_key,
            'client_secret': self.api_secret,
            'code': code
        }
        
        try:
            response = requests.post(url, json=data)
            response.raise_for_status()
            
            result = response.json()
            return result.get('access_token')
            
        except requests.exceptions.RequestException as e:
            print(f"Failed to get access token: {e}")
            return None
    
    def verify_webhook(self, data: bytes, hmac_header: str) -> bool:
        """Verify webhook authenticity"""
        expected_hmac = hmac.new(
            self.api_secret.encode('utf-8'),
            data,
            hashlib.sha256
        ).digest()
        
        # Shopify sends the HMAC as base64
        import base64
        expected_hmac_b64 = base64.b64encode(expected_hmac).decode('utf-8')
        
        return hmac.compare_digest(hmac_header, expected_hmac_b64)

