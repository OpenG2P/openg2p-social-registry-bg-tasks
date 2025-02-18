import logging
from datetime import datetime

import httpx
from openg2p_sr_models.models import (
    G2PQueIDGeneration,
    IDGenerationRequestStatus,
    IDGenerationUpdateStatus,
    ResPartner,
)
from sqlalchemy.orm import sessionmaker

from ..app import celery_app, get_engine
from ..config import Settings
from ..helpers import OAuthTokenService

_config = Settings.get_config()
_logger = logging.getLogger(_config.logging_default_logger_name)
_engine = get_engine()


@celery_app.task(name="id_generation_request_worker")
def id_generation_request_worker(registrant_id: str):
    _logger.info(f"Starting ID generation request for registrant_id: {registrant_id}")
    session_maker = sessionmaker(bind=_engine, expire_on_commit=False)

    with session_maker() as session:
        queue_entry = None
        try:
            # Fetch the queue entry
            queue_entry = (
                session.query(G2PQueIDGeneration)
                .filter(G2PQueIDGeneration.registrant_id == registrant_id)
                .first()
            )

            if not queue_entry:
                _logger.error(
                    f"No queue entry found for registrant_id: {registrant_id}"
                )
                return

            # Get OIDC token
            access_token = OAuthTokenService.get_component().get_oauth_token()
            _logger.info("Received access token")

            if not access_token:
                raise Exception("Failed to retrieve access token from token response")

            headers = {
                "Cookie": f"Authorization={access_token}",
                "Accept": "application/json",
            }

            response = httpx.get(_config.mosip_get_uin_url, headers=headers)
            if response.status_code != 200:
                raise Exception(
                    f"MOSIP Get UIN API call failed with status code {response.status_code}"
                )

            mosip_data = response.json()
            _logger.info(f"Received UIN data from MOSIP: {mosip_data}")
            uin = mosip_data.get("response")["uin"]

            if not uin:
                raise Exception("UIN not received from MOSIP")

            # Update res_partner.unique_id with the MOSIP Generated ID
            res_partner = (
                session.query(ResPartner).filter(ResPartner.id == registrant_id).first()
            )

            if not res_partner:
                raise Exception(
                    f"No res_partner entry found for registrant_id: {registrant_id}"
                )

            # Check if the UIN is already present in res_partner.unique_id
            existing_partner_with_uin = (
                session.query(ResPartner).filter(ResPartner.unique_id == uin).first()
            )

            if existing_partner_with_uin:
                raise Exception(
                    f"MOSIP ID {uin} is already present in res_partner.unique_id"
                )

            res_partner.unique_id = uin
            session.commit()

            # Update queue entry statuses
            queue_entry.number_of_attempts_request += 1
            queue_entry.id_generation_request_status = (
                IDGenerationRequestStatus.COMPLETED
            )
            queue_entry.id_generation_update_status = IDGenerationUpdateStatus.PENDING
            queue_entry.last_attempt_datetime_request = datetime.utcnow()
            queue_entry.last_attempt_error_code_request = None
            session.commit()

            _logger.info(
                f"ID generation request completed for registrant_id: {registrant_id}"
            )

        except Exception as e:
            error_message = f"Error during ID generation request for registrant_id {registrant_id}: {str(e)}"
            _logger.error(error_message)

            if queue_entry:
                queue_entry.number_of_attempts_request += 1
                queue_entry.last_attempt_datetime_request = datetime.utcnow()
                queue_entry.last_attempt_error_code_request = str(e)
                if (
                    queue_entry.number_of_attempts_request
                    >= _config.max_id_generation_request_attempts
                ):
                    queue_entry.id_generation_request_status = (
                        IDGenerationRequestStatus.FAILED
                    )
                session.commit()
        _logger.info(
            f"Completed ID generation request for registrant_id: {registrant_id}"
        )
