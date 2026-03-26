# sn_client.py - ServiceNow REST API Client

import logging
import requests
import time
from requests.auth import HTTPBasicAuth
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timedelta
import json

from ..inventory_class_catalog import inventory_class_tables
from .sn_fetch_config import (
    DEFAULT_BATCH_SIZE,
    MAX_BATCHES,
    INTER_BATCH_DELAY,
    MAX_RETRIES,
    RETRY_DELAYS,
    REQUEST_TIMEOUT,
    get_effective_config,
)

logger = logging.getLogger(__name__)


class ServiceNowClientError(Exception):
    """Custom exception for ServiceNow client errors"""
    pass


class ServiceNowClient:
    """
    ServiceNow REST API Client

    Handles authentication and provides methods to query ServiceNow tables.
    Designed to be extensible for additional query capabilities.
    """
    METADATA_CUSTOMIZATION_QUERY_MAX_LENGTH = 1500
    METADATA_CUSTOMIZATION_MAX_CLASSES_PER_QUERY = 60

    def __init__(
        self,
        instance_url: str,
        username: str,
        password: str,
        instance_id: Optional[int] = None,
        auth_type: str = "basic",
        oauth_manager: Optional[Any] = None,
    ):
        """
        Initialize the ServiceNow client.

        Args:
            instance_url: Full URL like https://dev12345.service-now.com
            username: ServiceNow username
            password: ServiceNow password
            instance_id: Optional local Instance.id for instance-scoped config overrides
            auth_type: "basic" or "oauth"
            oauth_manager: OAuthTokenManager instance (required when auth_type="oauth")
        """
        # Normalize URL (remove trailing slash)
        self.instance_url = instance_url.rstrip('/')
        self.username = username
        self.password = password
        self.auth_type = auth_type
        self._oauth_manager = oauth_manager
        self.session = requests.Session()

        if auth_type == "oauth" and oauth_manager:
            # Get initial token and set Bearer auth
            token = oauth_manager.get_access_token()
            self.session.headers.update({
                'Authorization': f'Bearer {token}',
                'Accept': 'application/json',
                'Content-Type': 'application/json',
            })
        else:
            # Default: Basic auth
            self.session.auth = HTTPBasicAuth(username, password)
            self.session.headers.update({
                'Accept': 'application/json',
                'Content-Type': 'application/json'
            })

        # Load effective fetch config from Integration Properties (AppConfig).
        # Falls back to compile-time defaults if DB is unavailable.
        self._cfg = get_effective_config(instance_id=instance_id)

    def _build_url(self, endpoint: str) -> str:
        """Build full URL for an API endpoint"""
        return f"{self.instance_url}/api/now/{endpoint}"

    def _refresh_oauth_token(self) -> bool:
        """Refresh the OAuth token and update the session header. Returns True on success."""
        if self.auth_type != "oauth" or not self._oauth_manager:
            return False
        try:
            token = self._oauth_manager.force_refresh()
            self.session.headers['Authorization'] = f'Bearer {token}'
            return True
        except Exception:
            return False

    def _oauth_get(self, url: str, **kwargs) -> requests.Response:
        """GET with automatic OAuth token refresh on 401."""
        response = self.session.get(url, **kwargs)
        if response.status_code == 401 and self._refresh_oauth_token():
            response = self.session.get(url, **kwargs)
        return response

    def _get(self, url: str, **kwargs) -> requests.Response:
        """Unified GET that uses OAuth retry when applicable."""
        if self.auth_type == "oauth":
            return self._oauth_get(url, **kwargs)
        return self.session.get(url, **kwargs)

    def _handle_response(self, response: requests.Response) -> Dict[str, Any]:
        """Handle API response and raise appropriate errors"""
        if response.status_code == 200:
            try:
                return response.json()
            except ValueError:
                raise ServiceNowClientError(
                    "API response was not JSON (possible auth/redirect issue)."
                )
        elif response.status_code == 401:
            raise ServiceNowClientError(
                "Authentication failed. Check username and password."
                if self.auth_type == "basic"
                else "Authentication failed. Check OAuth credentials (client ID/secret) and user account."
            )
        elif response.status_code == 403:
            # ServiceNow often returns a structured JSON error body for ACL failures.
            detail = ""
            try:
                body = response.json() or {}
                err = body.get("error") or {}
                msg = err.get("message") or ""
                det = err.get("detail") or ""
                if msg or det:
                    detail = f" ({msg}{' - ' if msg and det else ''}{det})"
            except Exception:
                detail = ""
            raise ServiceNowClientError(f"Access forbidden. Check user roles and permissions.{detail}")
        elif response.status_code == 404:
            raise ServiceNowClientError("Resource not found. Check the table name or endpoint.")
        else:
            raise ServiceNowClientError(
                f"API error: {response.status_code} - {response.text}"
            )

    def _safe_count(self, table: str, query: str = "", fallback_query: Optional[str] = None) -> int:
        try:
            return self.get_record_count(table, query)
        except ServiceNowClientError:
            if fallback_query:
                try:
                    return self.get_record_count(table, fallback_query)
                except ServiceNowClientError:
                    return -1
            return -1

    def _parse_sn_datetime(self, value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None

    def _month_start(self, dt: datetime) -> datetime:
        return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    def _add_month(self, dt: datetime) -> datetime:
        year = dt.year + (dt.month // 12)
        month = (dt.month % 12) + 1
        return dt.replace(year=year, month=month, day=1)

    def _get_global_scope_sys_id(self) -> Optional[str]:
        try:
            records = self.get_records(
                table="sys_scope",
                query="scope=global",
                fields=["sys_id"],
                limit=1
            )
            if records:
                return records[0].get("sys_id")
        except ServiceNowClientError:
            return None
        return None

    def test_connection(self) -> Dict[str, Any]:
        """
        Test connection to ServiceNow instance.

        Returns:
            Dict with connection status and instance info
        """
        try:
            version = "Unknown"

            # Try multiple approaches to get version
            # Approach 1: sys_properties with glide.buildname or glide.buildtag
            version_props = ["glide.buildtag", "glide.buildname", "glide.release.version"]
            for prop in version_props:
                try:
                    url = self._build_url("table/sys_properties")
                    params = {
                        "sysparm_query": f"name={prop}",
                        "sysparm_limit": 1,
                        "sysparm_fields": "name,value"
                    }
                    response = self._get(url, params=params, timeout=self._cfg['request_timeout'])
                    if response.status_code == 200:
                        data = response.json()
                        if data.get("result") and data["result"][0].get("value"):
                            version = data["result"][0]["value"]
                            break
                except:
                    continue

            # Approach 2: If still unknown, try sys_cluster_state
            if version == "Unknown":
                try:
                    url = self._build_url("table/sys_cluster_state")
                    params = {
                        "sysparm_limit": 1,
                        "sysparm_fields": "build_name"
                    }
                    response = self._get(url, params=params, timeout=self._cfg['request_timeout'])
                    if response.status_code == 200:
                        data = response.json()
                        if data.get("result") and data["result"][0].get("build_name"):
                            version = data["result"][0]["build_name"]
                except:
                    pass

            # Approach 3: At minimum, verify we can query something
            if version == "Unknown":
                # Just verify auth works by querying sys_user (current user)
                url = self._build_url("table/sys_user")
                params = {
                    "sysparm_query": f"user_name={self.username}",
                    "sysparm_limit": 1,
                    "sysparm_fields": "sys_id,user_name"
                }
                response = self._get(url, params=params, timeout=self._cfg['request_timeout'])
                self._handle_response(response)  # Will raise if auth fails

            return {
                "success": True,
                "message": "Connected successfully",
                "instance_url": self.instance_url,
                "version": version,
                "timestamp": datetime.utcnow().isoformat()
            }
        except requests.exceptions.ConnectionError:
            return {
                "success": False,
                "message": f"Could not connect to {self.instance_url}. Check the URL.",
                "timestamp": datetime.utcnow().isoformat()
            }
        except requests.exceptions.Timeout:
            return {
                "success": False,
                "message": "Connection timed out. Instance may be slow or unreachable.",
                "timestamp": datetime.utcnow().isoformat()
            }
        except ServiceNowClientError as e:
            return {
                "success": False,
                "message": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Unexpected error: {str(e)}",
                "timestamp": datetime.utcnow().isoformat()
            }

    def get_record_count(self, table: str, query: str = "") -> int:
        """
        Get count of records in a table matching a query.

        Args:
            table: Table name (e.g., "sys_script_include")
            query: Encoded query string (e.g., "active=true")

        Returns:
            Count of matching records
        """
        url = self._build_url(f"table/{table}")
        params = {
            "sysparm_limit": 1,
            "sysparm_fields": "sys_id",
            "sysparm_suppress_pagination_header": "false"
        }
        if query:
            params["sysparm_query"] = query

        response = self._get(url, params=params, timeout=self._cfg['request_timeout'])
        self._handle_response(response)

        # Get count from X-Total-Count header
        count = response.headers.get("X-Total-Count", "0")
        return int(count)

    def get_metadata_customization_count(
        self,
        since: Optional[datetime] = None,
        class_names: Optional[List[str]] = None,
        inclusive: bool = True,
    ) -> int:
        total = 0
        for query in self.build_metadata_customization_queries(
            since=since,
            class_names=class_names,
            inclusive=inclusive,
        ):
            total += self.get_record_count("sys_metadata_customization", query)
        return total

    def _build_query(self, parts: List[str]) -> str:
        cleaned = [part for part in parts if part]
        return "^".join(cleaned) if cleaned else ""

    def _watermark_filter(self, since: datetime, inclusive: bool = True) -> str:
        """Build sys_updated_on filter for delta queries.

        Args:
            since: Watermark datetime.
            inclusive: True for data pulls (>=), False for probes (>).
        """
        ts = since.strftime('%Y-%m-%d %H:%M:%S')
        op = ">=" if inclusive else ">"
        return f"sys_updated_on{op}{ts}"

    def build_update_set_query(
        self,
        since: Optional[datetime] = None,
        scope_filter: Optional[str] = None,
        inclusive: bool = True,
    ) -> str:
        query_parts = []
        if since:
            query_parts.append(self._watermark_filter(since, inclusive=inclusive))
        if scope_filter == "global":
            global_sys_id = self._get_global_scope_sys_id()
            if global_sys_id:
                query_parts.append(f"application={global_sys_id}")
            else:
                query_parts.append("application.scope=global")
        elif scope_filter == "scoped":
            global_sys_id = self._get_global_scope_sys_id()
            if global_sys_id:
                query_parts.append(f"application!={global_sys_id}")
            else:
                query_parts.append("application.scope!=global")
        return self._build_query(query_parts)

    def build_customer_update_xml_query(self, since: Optional[datetime] = None, inclusive: bool = True) -> str:
        query_parts = []
        if since:
            query_parts.append(self._watermark_filter(since, inclusive=inclusive))
        return self._build_query(query_parts)

    def build_version_history_query(
        self,
        since: Optional[datetime] = None,
        state_filter: Optional[str] = None,
        inclusive: bool = True,
    ) -> str:
        query_parts = []
        if since:
            query_parts.append(self._watermark_filter(since, inclusive=inclusive))
        if state_filter:
            query_parts.append(f"state={state_filter}")
        return self._build_query(query_parts)

    def build_metadata_customization_query(
        self,
        since: Optional[datetime] = None,
        class_names: Optional[List[str]] = None,
        inclusive: bool = True,
    ) -> str:
        queries = self.build_metadata_customization_queries(since=since, class_names=class_names, inclusive=inclusive)
        return queries[0] if queries else ""

    def build_metadata_customization_queries(
        self,
        since: Optional[datetime] = None,
        class_names: Optional[List[str]] = None,
        max_query_length: int = METADATA_CUSTOMIZATION_QUERY_MAX_LENGTH,
        max_classes_per_query: int = METADATA_CUSTOMIZATION_MAX_CLASSES_PER_QUERY,
        inclusive: bool = True,
    ) -> List[str]:
        query_parts = []
        if since:
            query_parts.append(self._watermark_filter(since, inclusive=inclusive))

        if not class_names:
            return [self._build_query(query_parts)]

        normalized_class_names: List[str] = []
        seen = set()
        for class_name in class_names:
            normalized = (class_name or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            normalized_class_names.append(normalized)

        if not normalized_class_names:
            return [self._build_query(query_parts)]

        class_filter_prefix = "sys_metadata.sys_class_nameIN"
        queries: List[str] = []
        chunk: List[str] = []

        for class_name in normalized_class_names:
            candidate_chunk = [*chunk, class_name]
            candidate_query = self._build_query(
                [*query_parts, f"{class_filter_prefix}{','.join(candidate_chunk)}"]
            )
            exceeds_class_limit = (
                max_classes_per_query > 0
                and len(candidate_chunk) > max_classes_per_query
                and len(chunk) > 0
            )
            exceeds_query_limit = (
                max_query_length > 0
                and len(candidate_query) > max_query_length
                and len(chunk) > 0
            )
            if exceeds_class_limit or exceeds_query_limit:
                queries.append(
                    self._build_query(
                        [*query_parts, f"{class_filter_prefix}{','.join(chunk)}"]
                    )
                )
                chunk = [class_name]
                continue
            chunk = candidate_chunk

        if chunk:
            queries.append(
                self._build_query(
                    [*query_parts, f"{class_filter_prefix}{','.join(chunk)}"]
                )
            )

        return queries if queries else [self._build_query(query_parts)]

    def build_app_file_types_query(self, since: Optional[datetime] = None, inclusive: bool = True) -> str:
        query_parts = []
        if since:
            query_parts.append(self._watermark_filter(since, inclusive=inclusive))
        return self._build_query(query_parts)

    def build_plugins_query(self, active_only: bool = False, since: Optional[datetime] = None, inclusive: bool = True) -> str:
        query_parts = []
        if since:
            query_parts.append(self._watermark_filter(since, inclusive=inclusive))
        if active_only:
            query_parts.append("active=true")
        return self._build_query(query_parts)

    def build_scopes_query(self, active_only: bool = False, since: Optional[datetime] = None, inclusive: bool = True) -> str:
        query_parts = []
        if since:
            query_parts.append(self._watermark_filter(since, inclusive=inclusive))
        if active_only:
            query_parts.append("active=true")
        return self._build_query(query_parts)

    def build_packages_query(self, since: Optional[datetime] = None, inclusive: bool = True) -> str:
        """Build query for sys_package records."""
        parts = []
        if since:
            parts.append(self._watermark_filter(since, inclusive=inclusive))
        return "^".join(parts)

    def build_applications_query(
        self,
        active_only: bool = False,
        since: Optional[datetime] = None,
        inclusive: bool = True,
    ) -> str:
        query_parts = []
        if since:
            query_parts.append(self._watermark_filter(since, inclusive=inclusive))
        if active_only:
            query_parts.append("active=true")
        return self._build_query(query_parts)

    def build_sys_db_object_query(self, since: Optional[datetime] = None, inclusive: bool = True) -> str:
        query_parts = []
        if since:
            query_parts.append(self._watermark_filter(since, inclusive=inclusive))
        return self._build_query(query_parts)

    def build_plugin_view_query(self, active_only: bool = False, since: Optional[datetime] = None, inclusive: bool = True) -> str:
        query_parts = []
        if since:
            query_parts.append(self._watermark_filter(since, inclusive=inclusive))
        if active_only:
            query_parts.append("active=true")
        return self._build_query(query_parts)

    def get_records(
        self,
        table: str,
        query: str = "",
        fields: Optional[List[str]] = None,
        limit: int = 100,
        offset: int = 0,
        order_by: Optional[str] = None,
        display_value: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get records from a ServiceNow table.

        Args:
            table: Table name
            query: Encoded query string
            fields: List of fields to return (None = all)
            limit: Maximum records to return
            offset: Starting offset for pagination

        Returns:
            List of record dictionaries
        """
        url = self._build_url(f"table/{table}")
        params = {
            "sysparm_limit": limit,
            "sysparm_offset": offset
        }
        if query:
            params["sysparm_query"] = query
        if fields:
            params["sysparm_fields"] = ",".join(fields)
        if order_by:
            params["sysparm_order_by"] = order_by
        if display_value is not None:
            params["sysparm_display_value"] = display_value

        response = self._get(url, params=params, timeout=self._cfg['request_timeout'])
        data = self._handle_response(response)

        return data.get("result", [])

    def _count_update_sets_by_scope(self) -> Dict[str, int]:
        global_sys_id = self._get_global_scope_sys_id()
        total_count = self._safe_count("sys_update_set", "")

        scoped_count = -1
        global_count = -1

        if global_sys_id:
            scoped_query = f"applicationISNOTEMPTY^application!={global_sys_id}"
            scoped_count = self._safe_count("sys_update_set", scoped_query)

            if total_count != -1 and scoped_count != -1:
                global_count = max(total_count - scoped_count, 0)

        if global_count == -1:
            global_count = self._safe_count("sys_update_set", "application.scope=global")
        if scoped_count == -1:
            scoped_count = self._safe_count("sys_update_set", "application.scope!=global")

        return {
            "global": global_count,
            "scoped": scoped_count,
            "total": total_count
        }

    def _count_update_xml_by_scope(self) -> Dict[str, int]:
        global_sys_id = self._get_global_scope_sys_id()
        total_count = self._safe_count("sys_update_xml", "")

        scoped_count = -1
        global_count = -1

        if global_sys_id:
            scoped_query = f"update_set.applicationISNOTEMPTY^update_set.application!={global_sys_id}"
            scoped_count = self._safe_count("sys_update_xml", scoped_query)
            if total_count != -1 and scoped_count != -1:
                global_count = max(total_count - scoped_count, 0)

        if global_count == -1:
            global_count = self._safe_count("sys_update_xml", "update_set.application.scope=global")
        if scoped_count == -1:
            scoped_count = self._safe_count("sys_update_xml", "update_set.application.scope!=global")

        return {
            "global": global_count,
            "scoped": scoped_count,
            "total": total_count
        }

    def _get_instance_dob(self) -> Tuple[Optional[datetime], Optional[str]]:
        # Primary: earliest Default update set in global scope
        default_queries = [
            "name=Default^application.scope=global",
            "name=Default^application.name=Global",
            "name=Default^application=global",
            "name=Default",
        ]
        for q in default_queries:
            try:
                records = self.get_records(
                    table="sys_update_set",
                    query=q,
                    fields=["sys_created_on"],
                    limit=1,
                    order_by="sys_created_on"
                )
                if records:
                    dob = self._parse_sn_datetime(records[0].get("sys_created_on"))
                    if dob:
                        return dob, "default_update_set_global"
            except ServiceNowClientError:
                continue

        # Fallback: earliest customer update xml record
        try:
            records = self.get_records(
                table="sys_update_xml",
                query="",
                fields=["sys_created_on"],
                limit=1,
                order_by="sys_created_on"
            )
            if records:
                dob = self._parse_sn_datetime(records[0].get("sys_created_on"))
                if dob:
                    return dob, "sys_update_xml_earliest"
        except ServiceNowClientError:
            pass

        return None, None

    def get_instance_metrics(self) -> Dict[str, Any]:
        """Compute and return instance metrics for comparison and analytics."""
        metrics: Dict[str, Any] = {}

        metrics["inventory"] = self.scan_inventory(scope="global")
        metrics["sys_metadata_customization_count"] = self._safe_count("sys_metadata_customization")

        task_tables = {
            "task": "task",
            "incident": "incident",
            "change_request": "change_request",
            "change_task": "change_task",
            "problem": "problem",
            "problem_task": "problem_task",
            "sc_req_item": "sc_req_item",
            "sc_task": "sc_task",
        }
        task_counts = {}
        for key, table in task_tables.items():
            count = self._safe_count(table)
            task_counts[key] = None if count == -1 else count

            archive_table = f"ar_{table}"
            archive_count = self._safe_count(archive_table)
            task_counts[f"archive_{key}"] = None if archive_count == -1 else archive_count
        metrics["task_counts"] = task_counts

        metrics["update_set_counts"] = self._count_update_sets_by_scope()
        metrics["sys_update_xml_counts"] = self._count_update_xml_by_scope()
        metrics["sys_update_xml_total"] = metrics["sys_update_xml_counts"].get("total")

        metrics["custom_scoped_app_counts"] = {
            "x": self._safe_count("sys_scope", "scopeSTARTSWITHx_"),
            "u": self._safe_count("sys_scope", "scopeSTARTSWITHu_")
        }

        metrics["custom_table_counts"] = {
            "x": self._safe_count("sys_db_object", "nameSTARTSWITHx_^active=true", "nameSTARTSWITHx_"),
            "u": self._safe_count("sys_db_object", "nameSTARTSWITHu_^active=true", "nameSTARTSWITHu_")
        }

        metrics["custom_field_counts"] = {
            "x": self._safe_count("sys_dictionary", "elementSTARTSWITHx_^active=true"),
            "u": self._safe_count("sys_dictionary", "elementSTARTSWITHu_^active=true")
        }

        dob, dob_source = self._get_instance_dob()
        metrics["instance_dob"] = dob
        metrics["instance_dob_source"] = dob_source
        if dob:
            age_years = round((datetime.utcnow() - dob).days / 365.25, 2)
            metrics["instance_age_years"] = age_years
        else:
            metrics["instance_age_years"] = None

        return metrics

    def get_monthly_counts(
        self,
        table: str,
        start_date: datetime,
        end_date: datetime,
        base_query: str = ""
    ) -> Tuple[List[str], List[int]]:
        """Get monthly counts for a table between dates."""
        labels: List[str] = []
        counts: List[int] = []

        current = self._month_start(start_date)
        end_month = self._month_start(end_date)

        while current <= end_month:
            next_month = self._add_month(current)
            start_str = current.strftime("%Y-%m-%d %H:%M:%S")
            end_str = next_month.strftime("%Y-%m-%d %H:%M:%S")

            query_parts = [f"sys_created_on>={start_str}", f"sys_created_on<{end_str}"]
            if base_query:
                query_parts.insert(0, base_query)
            query = "^".join(query_parts)

            count = self._safe_count(table, query)
            labels.append(current.strftime("%Y-%m"))
            counts.append(count if count != -1 else None)

            current = next_month

        return labels, counts

    def get_record(self, table: str, sys_id: str, fields: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
        """
        Get a single record by sys_id.

        Args:
            table: Table name
            sys_id: Record sys_id
            fields: List of fields to return

        Returns:
            Record dictionary or None if not found
        """
        url = self._build_url(f"table/{table}/{sys_id}")
        params = {}
        if fields:
            params["sysparm_fields"] = ",".join(fields)

        response = self._get(url, params=params, timeout=self._cfg['request_timeout'])

        if response.status_code == 404:
            return None

        data = self._handle_response(response)
        return data.get("result")

    # ============================================
    # SCAN METHODS - Add new scan capabilities here
    # ============================================

    def scan_inventory(self, scope: str = "global") -> Dict[str, int]:
        """
        Get inventory counts of key artifact types.

        Args:
            scope: "global", "scoped", or "all"

        Returns:
            Dictionary of artifact type -> count
        """
        tables_to_scan = inventory_class_tables(include_update_sets=True)

        # Build scope query
        scope_query = ""
        if scope == "global":
            scope_query = "sys_scope=global"
        elif scope == "scoped":
            scope_query = "sys_scope!=global"

        results = {}
        for name, table in tables_to_scan.items():
            try:
                count = self.get_record_count(table, scope_query)
                results[name] = count
            except ServiceNowClientError:
                results[name] = -1  # Indicate error/no access

        return results

    def scan_customizations(
        self,
        limit: int = 100,
        since: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get customized records from sys_update_xml.

        Args:
            limit: Maximum records to return
            since: ISO date string to filter by (e.g., "2024-01-01")

        Returns:
            List of customization records
        """
        query = "action!=DELETE"
        if since:
            query += f"^sys_created_on>={since}"

        fields = [
            "sys_id", "name", "type", "target_name", "action",
            "sys_created_on", "sys_created_by", "update_set"
        ]

        return self.get_records(
            table="sys_update_xml",
            query=query,
            fields=fields,
            limit=limit
        )

    def scan_script_includes(
        self,
        scope: str = "global",
        active_only: bool = True,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get script includes for analysis.

        Args:
            scope: "global", "scoped", or "all"
            active_only: Only return active script includes
            limit: Maximum records to return

        Returns:
            List of script include records
        """
        query_parts = []
        if scope == "global":
            query_parts.append("sys_scope=global")
        elif scope == "scoped":
            query_parts.append("sys_scope!=global")
        if active_only:
            query_parts.append("active=true")

        query = "^".join(query_parts)

        fields = [
            "sys_id", "name", "api_name", "script", "active",
            "sys_scope", "sys_package", "sys_class_name",
            "sys_updated_on", "sys_updated_by", "sys_created_on", "sys_created_by"
        ]

        return self.get_records(
            table="sys_script_include",
            query=query,
            fields=fields,
            limit=limit
        )

    def scan_business_rules(
        self,
        table_name: Optional[str] = None,
        active_only: bool = True,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get business rules for analysis.

        Args:
            table_name: Filter by target table (optional)
            active_only: Only return active rules
            limit: Maximum records to return

        Returns:
            List of business rule records
        """
        query_parts = []
        if table_name:
            query_parts.append(f"collection={table_name}")
        if active_only:
            query_parts.append("active=true")

        query = "^".join(query_parts)

        fields = [
            "sys_id", "name", "collection", "when", "order", "script",
            "active", "advanced", "sys_scope",
            "sys_updated_on", "sys_updated_by"
        ]

        return self.get_records(
            table="sys_script",
            query=query,
            fields=fields,
            limit=limit
        )

    # ============================================
    # DATA PULL METHODS (Generator-based batched iteration)
    # ============================================

    # ------------------------------------------------------------------
    # Retry helper (shared by _iterate_batches and callers)
    # ------------------------------------------------------------------

    def _fetch_with_retry(
        self,
        table: str,
        query: str,
        fields: Optional[List[str]],
        batch_size: int,
        offset: int,
        order_by: Optional[str],
    ) -> List[Dict[str, Any]]:
        """Fetch a single batch with retry / back-off.

        Non-transient errors (``ServiceNowClientError`` — auth, ACL, 404)
        are re-raised immediately.  Transient errors are retried up to
        ``MAX_RETRIES`` times with the delays defined in ``RETRY_DELAYS``.
        """
        for attempt in range(MAX_RETRIES):
            try:
                return self.get_records(
                    table=table,
                    query=query,
                    fields=fields,
                    limit=batch_size,
                    offset=offset,
                    order_by=order_by,
                )
            except ServiceNowClientError:
                # Non-transient — don't retry.
                raise
            except Exception as exc:
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                    logger.warning(
                        "Batch at offset %d attempt %d failed (%s), retrying in %ds",
                        offset, attempt + 1, exc, delay,
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        "Batch at offset %d failed after %d attempts: %s",
                        offset, MAX_RETRIES, exc,
                    )
                    raise

        # Should not reach here, but satisfy type checker.
        return []  # pragma: no cover

    # ------------------------------------------------------------------
    # Batched pagination generator
    # ------------------------------------------------------------------

    def _iterate_batches(
        self,
        table: str,
        query: str = "",
        fields: Optional[List[str]] = None,
        batch_size: Optional[int] = None,
        order_by: str = "sys_updated_on",
        inter_batch_delay: Optional[float] = None,
        max_batches: Optional[int] = None,
        order_desc: bool = False,
    ):
        """Generator that yields batches of records using offset pagination.

        Values for batch_size, inter_batch_delay, and max_batches are resolved
        at runtime from the Integration Properties UI (AppConfig).  Pass
        explicit values to override.

        Args:
            table: ServiceNow table name
            query: Encoded query string (filter only; ORDER BY is added here)
            fields: List of fields to return (None = all fields)
            batch_size: Records per API call (None = from properties)
            order_by: Field to order by for consistent pagination
            inter_batch_delay: Seconds between successive API calls (None = from properties)
            max_batches: Safety cap — stop after this many batches (None = from properties)
            order_desc: When True, use ORDERBYDESC instead of ORDERBY (newest-first)

        Yields:
            List[Dict] — one batch of records at a time
        """
        # Resolve None → effective config from Integration Properties.
        if batch_size is None:
            batch_size = self._cfg['batch_size']
        if inter_batch_delay is None:
            inter_batch_delay = self._cfg['inter_batch_delay']
        if max_batches is None:
            max_batches = self._cfg['max_batches']

        # Append ORDER BY to the query string (SN encoded-query format).
        # This is in addition to sysparm_order_by; SN honours whichever
        # it encounters first.
        # When order_desc=True, use ORDERBYDESC for newest-first ordering.
        order_keyword = "ORDERBYDESC" if order_desc else "ORDERBY"
        effective_query = query or ""
        if order_by and f"{order_keyword}{order_by}" not in effective_query:
            effective_query = (
                f"{effective_query}^{order_keyword}{order_by}"
                if effective_query
                else f"{order_keyword}{order_by}"
            )

        offset = 0
        batch_num = 0

        while batch_num < max_batches:
            batch = self._fetch_with_retry(
                table, effective_query, fields,
                batch_size, offset, order_by,
            )
            if not batch:
                break

            yield batch
            batch_num += 1

            if len(batch) < batch_size:
                break

            offset += batch_size

            # Polite pacing between API calls.
            if inter_batch_delay > 0:
                time.sleep(inter_batch_delay)

        if batch_num >= max_batches:
            logger.warning(
                "Hit MAX_BATCHES (%d) for table %s — %d rows fetched",
                max_batches, table, batch_num * batch_size,
            )

    def iterate_delta_keyset(
        self,
        table: str,
        watermark: Optional[datetime] = None,
        base_query: str = "",
        fields: Optional[List[str]] = None,
        batch_size: Optional[int] = None,
        inter_batch_delay: Optional[float] = None,
        max_batches: Optional[int] = None,
    ):
        """Yield records via keyset pagination for delta pulls.

        This is additive to the existing offset iterator and is intended for
        deterministic delta traversal under timestamp ties:
        - Cursor sort: ``sys_updated_on ASC, sys_id ASC``
        - Cursor filter after each batch:
          ``sys_updated_on>{ts}^ORsys_updated_on={ts}^sys_id>{sys_id}``
        """
        # Resolve None → effective config from Integration Properties.
        if batch_size is None:
            batch_size = self._cfg['batch_size']
        if inter_batch_delay is None:
            inter_batch_delay = self._cfg['inter_batch_delay']
        if max_batches is None:
            max_batches = self._cfg['max_batches']

        watermark_str = None
        if watermark is not None:
            watermark_str = watermark.strftime("%Y-%m-%d %H:%M:%S")

        cursor_updated_on: Optional[str] = None
        cursor_sys_id: Optional[str] = None
        batch_num = 0

        effective_fields = list(fields) if fields else None
        if effective_fields is not None:
            if "sys_updated_on" not in effective_fields:
                effective_fields.append("sys_updated_on")
            if "sys_id" not in effective_fields:
                effective_fields.append("sys_id")

        while batch_num < max_batches:
            query_parts: List[str] = []
            if base_query:
                query_parts.append(base_query)

            if cursor_updated_on and cursor_sys_id:
                query_parts.append(
                    f"sys_updated_on>{cursor_updated_on}^ORsys_updated_on={cursor_updated_on}^sys_id>{cursor_sys_id}"
                )
            elif watermark_str:
                query_parts.append(f"sys_updated_on>={watermark_str}")

            effective_query = self._build_query(query_parts)
            if "ORDERBYsys_updated_on" not in effective_query:
                effective_query = (
                    f"{effective_query}^ORDERBYsys_updated_on"
                    if effective_query
                    else "ORDERBYsys_updated_on"
                )
            if "ORDERBYsys_id" not in effective_query:
                effective_query = f"{effective_query}^ORDERBYsys_id"

            batch = self._fetch_with_retry(
                table=table,
                query=effective_query,
                fields=effective_fields,
                batch_size=batch_size,
                offset=0,
                order_by=None,  # ORDER BY is encoded in query for two-key sort.
            )
            if not batch:
                break

            yield batch
            batch_num += 1

            last = batch[-1]
            next_updated_on = last.get("sys_updated_on")
            next_sys_id = last.get("sys_id")
            if not next_updated_on or not next_sys_id:
                logger.warning(
                    "Keyset pagination stopped early for %s: missing cursor fields in last record",
                    table,
                )
                break

            cursor_updated_on = str(next_updated_on)
            cursor_sys_id = str(next_sys_id)

            if len(batch) < batch_size:
                break
            if inter_batch_delay > 0:
                time.sleep(inter_batch_delay)

        if batch_num >= max_batches:
            logger.warning(
                "Hit MAX_BATCHES (%d) in keyset iterator for table %s",
                max_batches,
                table,
            )

    def pull_update_sets(
        self,
        since: Optional[datetime] = None,
        batch_size: Optional[int] = None,
        scope_filter: Optional[str] = None,
        order_desc: bool = False,
    ):
        """
        Pull update sets from ServiceNow using batched pagination.

        Args:
            since: Only pull records updated since this datetime (for delta pulls)
            batch_size: Number of records per API call
            scope_filter: Filter by scope ("global", "scoped", or None for all)
            order_desc: When True, order newest-first (ORDERBYDESC)

        Yields:
            Batches of update set records
        """
        # Fetch all fields to retain full payload
        fields = None

        query = self.build_update_set_query(since=since, scope_filter=scope_filter)

        for batch in self._iterate_batches(
            table="sys_update_set",
            query=query,
            fields=fields,
            batch_size=batch_size,
            order_desc=order_desc,
        ):
            yield batch

    def pull_customer_update_xml(
        self,
        since: Optional[datetime] = None,
        batch_size: Optional[int] = None,
        include_payload: bool = False,
        order_desc: bool = False,
    ):
        """
        Pull customer update XML records using batched pagination.

        Args:
            since: Only pull records updated since this datetime
            batch_size: Number of records per API call
            include_payload: Whether to include the full XML payload (large!)
            order_desc: When True, order newest-first (ORDERBYDESC)

        Yields:
            Batches of customer update XML records
        """
        fields = [
            "sys_id", "name", "action", "type", "target_name",
            "update_set", "category", "update_guid", "update_guid_history",
            "application", "comments", "replace_on_upgrade", "remote_update_set",
            "update_domain", "view", "table", "sys_recorded_at",
            "sys_created_on", "sys_created_by", "sys_updated_on", "sys_updated_by",
            "sys_mod_count", "payload_hash"
        ]

        if include_payload:
            fields.append("payload")

        query = self.build_customer_update_xml_query(since=since)

        for batch in self._iterate_batches(
            table="sys_update_xml",
            query=query,
            fields=fields,
            batch_size=batch_size,
            order_desc=order_desc,
        ):
            yield batch

    def pull_version_history(
        self,
        since: Optional[datetime] = None,
        batch_size: Optional[int] = None,
        state_filter: Optional[str] = None,
        order_desc: bool = False,
    ):
        """
        Pull version history records using batched pagination.

        Args:
            since: Only pull records since this datetime
            batch_size: Number of records per API call
            state_filter: Filter by state (e.g., "current" for head versions)
            order_desc: When True, order newest-first (ORDERBYDESC)

        Yields:
            Batches of version history records
        """
        # Fetch all fields to retain full payload
        fields = None

        query = self.build_version_history_query(since=since, state_filter=state_filter)

        # When pulling all states, sort by state first so "current" records
        # arrive before "previous" etc.  Within each state group, sort by
        # sys_recorded_at for consistent pagination.
        order = "state,sys_recorded_at" if not state_filter else "sys_recorded_at"

        for batch in self._iterate_batches(
            table="sys_update_version",
            query=query,
            fields=fields,
            batch_size=batch_size,
            order_by=order,
            order_desc=order_desc,
        ):
            yield batch

    def pull_metadata_customizations(
        self,
        since: Optional[datetime] = None,
        batch_size: Optional[int] = None,
        class_names: Optional[List[str]] = None,
        order_desc: bool = False,
    ):
        """
        Pull metadata customization records using batched pagination.

        Args:
            since: Only pull records updated since this datetime
            batch_size: Number of records per API call
            class_names: Optional list of class names to filter by
            order_desc: When True, order newest-first (ORDERBYDESC)

        Yields:
            Batches of metadata customization records
        """
        # Fetch all fields to retain full payload
        fields = None

        for query in self.build_metadata_customization_queries(since=since, class_names=class_names):
            for batch in self._iterate_batches(
                table="sys_metadata_customization",
                query=query,
                fields=fields,
                batch_size=batch_size,
                order_desc=order_desc,
            ):
                yield batch

    def pull_app_file_types(
        self,
        since: Optional[datetime] = None,
        batch_size: Optional[int] = None,
        order_desc: bool = False,
    ):
        """
        Pull app file type records from sys_app_file_type.

        Args:
            since: Only pull records updated since this datetime
            batch_size: Number of records per API call
            order_desc: When True, order newest-first (ORDERBYDESC)

        Yields:
            Batches of app file type records
        """
        # Fetch all fields to retain full payload.
        fields = None

        query = self.build_app_file_types_query(since=since)

        for batch in self._iterate_batches(
            table="sys_app_file_type",
            query=query,
            fields=fields,
            batch_size=batch_size,
            order_desc=order_desc,
        ):
            yield batch

    def pull_plugins(
        self,
        batch_size: Optional[int] = None,
        active_only: bool = False,
        since: Optional[datetime] = None,
        order_desc: bool = False,
    ):
        """
        Pull plugin records from sys_plugins.

        Args:
            batch_size: Number of records per API call
            active_only: Only pull active plugins
            since: Only pull records updated since this datetime
            order_desc: When True, order newest-first (ORDERBYDESC)

        Yields:
            Batches of plugin records
        """
        # Fetch all fields to retain full payload
        fields = None

        query = self.build_plugins_query(active_only=active_only, since=since)

        for batch in self._iterate_batches(
            table="sys_plugins",
            query=query,
            fields=fields,
            batch_size=batch_size,
            order_by="name",
            order_desc=order_desc,
        ):
            yield batch

    def pull_scopes(
        self,
        batch_size: Optional[int] = None,
        active_only: bool = False,
        since: Optional[datetime] = None,
        order_desc: bool = False,
    ):
        """
        Pull application scope records from sys_scope.

        Args:
            batch_size: Number of records per API call
            active_only: Only pull active scopes
            since: Only pull records updated since this datetime
            order_desc: When True, order newest-first (ORDERBYDESC)

        Yields:
            Batches of scope records
        """
        # Fetch all fields to retain full payload
        fields = None

        query = self.build_scopes_query(active_only=active_only, since=since)

        for batch in self._iterate_batches(
            table="sys_scope",
            query=query,
            fields=fields,
            batch_size=batch_size,
            order_by="scope",
            order_desc=order_desc,
        ):
            yield batch

    def pull_packages(
        self,
        since: Optional[datetime] = None,
        batch_size: Optional[int] = None,
        order_desc: bool = False,
    ):
        """
        Pull package records from sys_package.

        Note: sys_package is NOT OOTB web-accessible. If this fails with 403/404,
        the admin needs to enable "Allow access to this table via web services"
        on the sys_db_object record for sys_package.

        Args:
            since: Only pull records updated since this datetime
            batch_size: Number of records per API call
            order_desc: When True, order newest-first (ORDERBYDESC)

        Yields:
            Batches of package records
        """
        # Fetch all fields to retain full payload
        fields = None

        query = self.build_packages_query(since=since)

        for batch in self._iterate_batches(
            table="sys_package",
            query=query,
            fields=fields,
            batch_size=batch_size,
            order_by="name",
            order_desc=order_desc,
        ):
            yield batch

    def pull_applications(
        self,
        batch_size: Optional[int] = None,
        active_only: bool = False,
        since: Optional[datetime] = None,
        order_desc: bool = False,
    ):
        """
        Pull application records from sys_app.

        Args:
            batch_size: Number of records per API call
            active_only: Only pull active apps
            since: Only pull records updated since this datetime
            order_desc: When True, order newest-first (ORDERBYDESC)

        Yields:
            Batches of application records
        """
        fields = None
        query = self.build_applications_query(active_only=active_only, since=since)

        for batch in self._iterate_batches(
            table="sys_app",
            query=query,
            fields=fields,
            batch_size=batch_size,
            order_by="name",
            order_desc=order_desc,
        ):
            yield batch

    def pull_sys_db_object(
        self,
        since: Optional[datetime] = None,
        batch_size: Optional[int] = None,
        order_desc: bool = False,
    ):
        """
        Pull table definitions from sys_db_object.

        Args:
            since: Only pull records updated since this datetime
            batch_size: Number of records per API call
            order_desc: When True, order newest-first (ORDERBYDESC)

        Yields:
            Batches of sys_db_object records (all fields)
        """
        query = self.build_sys_db_object_query(since=since)

        for batch in self._iterate_batches(
            table="sys_db_object",
            query=query,
            fields=None,  # all fields
            batch_size=batch_size,
            order_by="sys_updated_on",
            order_desc=order_desc,
        ):
            yield batch

    def pull_plugin_view(
        self,
        batch_size: Optional[int] = None,
        active_only: bool = False,
        since: Optional[datetime] = None,
        order_desc: bool = False,
    ):
        """
        Pull plugin view records from v_plugin.

        Args:
            batch_size: Number of records per API call
            active_only: Only pull active plugins
            since: Only pull records updated since this datetime
            order_desc: When True, order newest-first (ORDERBYDESC)

        Yields:
            Batches of v_plugin records
        """
        fields = None
        query = self.build_plugin_view_query(active_only=active_only, since=since)

        for batch in self._iterate_batches(
            table="v_plugin",
            query=query,
            fields=fields,
            batch_size=batch_size,
            order_by="name",
            order_desc=order_desc,
        ):
            yield batch
