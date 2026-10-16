"""Web Push notification manager using VAPID (RFC 8292).

Delivers real background push notifications directly to Apple APNs and Google FCM,
waking up sleeping phones and smart watches even when screens are locked and browser
tabs are closed.

Subscribers are persisted as individual JSON files in OCI Object Storage under
the 'subscriptions/' bucket prefix via Pre-Authenticated Requests (PAR).
"""

import json
import logging
import os
from pathlib import Path
from typing import List, Dict, Any, Optional

log = logging.getLogger(__name__)


class WebPushManager:
    """Manages VAPID keys, subscriber retrieval from S3/OCI, and push dispatch."""

    def __init__(
        self,
        vapid_private_key_path: Optional[str] = None,
        vapid_claim_email: Optional[str] = None,
        s3_client: Any = None,
        s3_bucket: Optional[str] = None,
    ):
        self.private_key_path = vapid_private_key_path or os.environ.get(
            'VAPID_PRIVATE_KEY_PATH', 'data/vapid_private.pem'
        )
        self.claim_email = vapid_claim_email or os.environ.get(
            'VAPID_CLAIM_EMAIL', 'mailto:tracker@rinkside.ca'
        )
        self.s3_client = s3_client
        self.s3_bucket = s3_bucket or os.environ.get('S3_BUCKET_NAME', 'rinkside')

    def is_configured(self) -> bool:
        """Check if VAPID private key exists and S3 client is available."""
        p = Path(self.private_key_path)
        return p.exists() and self.s3_client is not None

    def get_subscriptions(self) -> List[Dict[str, Any]]:
        """Fetch all subscriber payloads from OCI Object Storage under subscriptions/ prefix."""
        if not self.s3_client or not self.s3_bucket:
            return []

        subscriptions = []
        try:
            resp = self.s3_client.list_objects_v2(
                Bucket=self.s3_bucket,
                Prefix='subscriptions/'
            )
            for item in resp.get('Contents', []):
                key = item['Key']
                if not key.endswith('.json'):
                    continue
                try:
                    obj = self.s3_client.get_object(Bucket=self.s3_bucket, Key=key)
                    data = json.loads(obj['Body'].read().decode('utf-8'))
                    data['_key'] = key
                    subscriptions.append(data)
                except Exception as e:
                    log.warning(f"Failed to read subscription {key}: {e}")
        except Exception as e:
            log.warning(f"Failed to list subscriptions from {self.s3_bucket}: {e}")

        return subscriptions

    def delete_subscription(self, key: str):
        """Remove invalid or expired subscription (HTTP 410 Gone / 404 Not Found)."""
        if not self.s3_client or not self.s3_bucket:
            return
        try:
            self.s3_client.delete_object(Bucket=self.s3_bucket, Key=key)
            log.info(f"Deleted expired subscription: {key}")
        except Exception as e:
            log.warning(f"Failed to delete subscription {key}: {e}")

    def send_push(self, sub_record: Dict[str, Any], payload: Dict[str, Any]) -> bool:
        """Send a single Web Push notification via pywebpush."""
        try:
            import pywebpush
        except ImportError:
            log.warning("pywebpush is not installed. Push notifications skipped.")
            return False

        sub_info = sub_record.get('subscription')
        if not sub_info or not sub_info.get('endpoint'):
            return False

        try:
            pywebpush.webpush(
                subscription_info=sub_info,
                data=json.dumps(payload),
                vapid_private_key=str(Path(self.private_key_path).resolve()),
                vapid_claims={"sub": self.claim_email}
            )
            return True
        except pywebpush.WebPushException as ex:
            # Check for expired/unsubscribed tokens
            status_code = getattr(ex, 'response', None)
            code = status_code.status_code if status_code else None
            if code in (404, 410) or '410 Gone' in str(ex) or '404' in str(ex):
                log.info(f"Subscription expired ({code or 410}). Cleaning up...")
                if sub_record.get('_key'):
                    self.delete_subscription(sub_record['_key'])
            else:
                log.warning(f"WebPush failed: {ex}")
            return False
        except Exception as e:
            log.warning(f"Unexpected WebPush error: {e}")
            return False

    def broadcast_events(self, events: List[Dict[str, Any]]) -> int:
        """Broadcast live game events to all matching subscribers."""
        if not events or not self.is_configured():
            return 0

        # Filter for match events that deserve a push alert
        match_events = [
            e for e in events
            if e.get('type') in ('goal', 'final', 'start') or
            (e.get('headline') and any(
                w in e['headline'].upper() for w in ('STARTED', 'FINAL', 'SCORE UPDATE')
            ))
        ]

        if not match_events:
            return 0

        subs = self.get_subscriptions()
        if not subs:
            return 0

        sent_count = 0
        for evt in match_events:
            game_id = str(evt.get('game_id') or '')
            payload = {
                'title': evt.get('headline', '🏒 Rinkside Alert'),
                'body': evt.get('detail') or 'Live tournament game update.',
                'tag': f"rinkside-evt-{game_id or 'all'}-{abs(hash(evt.get('headline', '')))}",
                'url': './'
            }

            for sub in subs:
                alerts_enabled = sub.get('alerts_enabled', True)
                subbed_games = [str(g) for g in sub.get('games', [])]
                
                # Check if this subscriber wants this alert
                is_subbed = bool(game_id and game_id in subbed_games)
                if not (alerts_enabled or is_subbed):
                    continue

                if self.send_push(sub, payload):
                    sent_count += 1

        log.info(f"Dispatched {sent_count} Web Push notification(s) across {len(subs)} device(s).")
        return sent_count
