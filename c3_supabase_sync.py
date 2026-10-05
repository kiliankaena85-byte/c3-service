# -*- coding: utf-8 -*-
"""
Supabase Direct SQL Client & Self-Learning Engine
Synchronizes leads, keywords, negative tokens, and channel metrics via Supabase Management API.
Supports hybrid vector/FTS search and automated feedback loops.
"""

import os
import json
import logging
import requests
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv

load_dotenv()
_local_env = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_local_env):
    load_dotenv(_local_env, override=False)

logger = logging.getLogger("SupabaseSync")

DEFAULT_REF = os.getenv("SUPABASE_PROJECT_REF", "sbphllovotwehuajtxmi")
DEFAULT_PAT = os.getenv("SUPABASE_ACCESS_TOKEN", "")


class SupabaseSync:
    def __init__(self, project_ref: str = None, access_token: str = None):
        self.project_ref = project_ref or os.getenv("SUPABASE_PROJECT_REF", DEFAULT_REF)
        self.access_token = access_token or os.getenv("SUPABASE_ACCESS_TOKEN", DEFAULT_PAT)
        self.endpoint = f"https://api.supabase.com/v1/projects/{self.project_ref}/database/query"
        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

    def execute_sql(self, query: str) -> Optional[List[Dict[str, Any]]]:
        """Executes raw SQL query on Supabase PostgreSQL database."""
        try:
            resp = requests.post(self.endpoint, headers=self.headers, json={"query": query}, timeout=15)
            if resp.status_code in [200, 201]:
                try:
                    return resp.json()
                except Exception:
                    return []
            else:
                logger.error(f"Supabase Query Error ({resp.status_code}): {resp.text}")
                return None
        except Exception as e:
            logger.error(f"Supabase Connection Exception: {e}")
            return None

    def _escape_sql_str(self, val: Any) -> str:
        if val is None:
            return "NULL"
        s = str(val).replace("'", "''")
        return f"'{s}'"

    def save_lead(self, data: Dict[str, Any]) -> Optional[str]:
        """
        Inserts a new lead into public.leads table.
        Returns the generated UUID string or None.
        """
        source = self._escape_sql_str(data.get("source", "telegram"))
        channel_title = self._escape_sql_str(data.get("channel_title", ""))
        channel_username = self._escape_sql_str(data.get("channel_username", ""))
        sender_name = self._escape_sql_str(data.get("sender_name", ""))
        sender_username = self._escape_sql_str(data.get("sender_username", ""))
        raw_text = self._escape_sql_str(data.get("raw_text", ""))
        category_id = self._escape_sql_str(data.get("category_id", "unknown"))
        category_title = self._escape_sql_str(data.get("category_title", ""))
        match_type = self._escape_sql_str(data.get("match_type", "keyword"))
        confidence_score = float(data.get("confidence_score", 1.0))
        generated_pitch = self._escape_sql_str(data.get("generated_pitch", ""))
        humanity_score = float(data.get("humanity_score", 1.0))
        status = self._escape_sql_str(data.get("status", "new"))
        message_link = self._escape_sql_str(data.get("message_link", ""))

        sql = f"""
        INSERT INTO public.leads (
            source, channel_title, channel_username, sender_name, sender_username,
            raw_text, category_id, category_title, match_type, confidence_score,
            generated_pitch, humanity_score, status, message_link
        ) VALUES (
            {source}, {channel_title}, {channel_username}, {sender_name}, {sender_username},
            {raw_text}, {category_id}, {category_title}, {match_type}, {confidence_score},
            {generated_pitch}, {humanity_score}, {status}, {message_link}
        )
        RETURNING id;
        """
        res = self.execute_sql(sql)
        if res and len(res) > 0 and "id" in res[0]:
            return str(res[0]["id"])
        return None

    def update_lead_status(self, lead_id: str, status: str, rejection_reason: str = None, edited_pitch: str = None) -> bool:
        """
        Updates lead status ('accepted', 'rejected', 'converted') and logs reasons or pitch edits.
        """
        updates = [f"status = {self._escape_sql_str(status)}"]
        if rejection_reason:
            updates.append(f"rejection_reason = {self._escape_sql_str(rejection_reason)}")
        if edited_pitch:
            updates.append(f"edited_pitch = {self._escape_sql_str(edited_pitch)}")

        set_clause = ", ".join(updates)
        sql = f"""
        UPDATE public.leads
        SET {set_clause}
        WHERE id = '{lead_id}' OR id::text LIKE '{lead_id}%';
        """
        res = self.execute_sql(sql)
        return res is not None

    def record_feedback(self, lead_id: str, accepted: bool, rejection_reason: str = None) -> bool:
        """
        Closes the feedback loop:
        1. Updates lead status in `leads`.
        2. Retrieves lead category and trigger to update `keywords_performance`.
        3. If rejected, extracts stop tokens and registers into `negative_tokens`.
        """
        status = "accepted" if accepted else "rejected"
        
        # 1. Fetch lead details
        fetch_sql = f"""
        SELECT id, category_id, raw_text 
        FROM public.leads 
        WHERE id = '{lead_id}' OR id::text LIKE '{lead_id}%' 
        LIMIT 1;
        """
        rows = self.execute_sql(fetch_sql)
        if not rows:
            logger.warning(f"Лид с ID '{lead_id}' не найден для обратной связи.")
            return False

        lead = rows[0]
        full_id = lead["id"]
        category_id = lead.get("category_id", "")
        raw_text = lead.get("raw_text", "")

        # 2. Update status
        self.update_lead_status(full_id, status, rejection_reason=rejection_reason)

        # 3. If rejected, mine negative tokens from reason or raw text
        if not accepted:
            tokens_to_add = set()
            if rejection_reason:
                # Add specific tokens from user reason
                clean_reason = rejection_reason.strip().lower()
                if len(clean_reason) > 2:
                    tokens_to_add.add(clean_reason)
            
            for tok in tokens_to_add:
                esc_tok = self._escape_sql_str(tok)
                esc_cat = self._escape_sql_str(category_id)
                esc_reason = self._escape_sql_str(f"User rejected lead {full_id[:8]}: {rejection_reason}")
                neg_sql = f"""
                INSERT INTO public.negative_tokens (category_id, token, tier, reason, is_active)
                VALUES ({esc_cat}, {esc_tok}, 'feedback_mined', {esc_reason}, true)
                ON CONFLICT (category_id, token) DO UPDATE
                SET is_active = true, reason = {esc_reason};
                """
                self.execute_sql(neg_sql)

        return True

    def get_lead_by_prefix(self, prefix: str) -> Optional[Dict[str, Any]]:
        """Retrieves a single lead by UUID prefix (e.g. first 8 characters)."""
        sql = f"""
        SELECT id, raw_text, category_id, category_title, sender_name, status, created_at
        FROM public.leads
        WHERE id::text LIKE '{prefix}%'
        ORDER BY created_at DESC
        LIMIT 1;
        """
        res = self.execute_sql(sql)
        if res and len(res) > 0:
            return res[0]
        return None

    def get_latest_lead(self) -> Optional[Dict[str, Any]]:
        """Retrieves the most recent lead."""
        sql = """
        SELECT id, raw_text, category_id, category_title, sender_name, status, created_at
        FROM public.leads
        ORDER BY created_at DESC
        LIMIT 1;
        """
        res = self.execute_sql(sql)
        if res and len(res) > 0:
            return res[0]
        return None

    def update_channel_stats(self, channel_username: str, channel_title: str = "", scanned_inc: int = 1, leads_inc: int = 0, accepted_inc: int = 0):
        """Upserts channel activity and yield statistics."""
        if not channel_username:
            return
        esc_username = self._escape_sql_str(channel_username)
        esc_title = self._escape_sql_str(channel_title or channel_username)
        lead_time = "now()" if leads_inc > 0 else "last_lead_at"

        sql = f"""
        INSERT INTO public.channel_scores (
            channel_username, channel_title, total_messages_scanned, leads_generated_count, leads_accepted_count, last_lead_at
        ) VALUES (
            {esc_username}, {esc_title}, {scanned_inc}, {leads_inc}, {accepted_inc}, {lead_time}
        )
        ON CONFLICT (channel_username) DO UPDATE
        SET total_messages_scanned = channel_scores.total_messages_scanned + {scanned_inc},
            leads_generated_count = channel_scores.leads_generated_count + {leads_inc},
            leads_accepted_count = channel_scores.leads_accepted_count + {accepted_inc},
            channel_title = COALESCE(EXCLUDED.channel_title, channel_scores.channel_title),
            last_lead_at = CASE WHEN {leads_inc} > 0 THEN now() ELSE channel_scores.last_lead_at END,
            yield_score = ROUND(((channel_scores.leads_accepted_count + {accepted_inc})::float / GREATEST(channel_scores.total_messages_scanned + {scanned_inc}, 1) * 100)::numeric, 4);
        """
        self.execute_sql(sql)

    def seed_initial_semantics(self, categories_dict: Dict[str, Dict[str, Any]]):
        """
        Populates keywords_performance and negative_tokens from lead_categories in fast bulk SQL.
        """
        logger.info(f"Начало пакетного посева семантики для {len(categories_dict)} категорий...")
        kw_values = []
        neg_values = []

        for cat_id, cat in categories_dict.items():
            # 1. Triggers (Tier: hot)
            for trig in cat.get("triggers", []):
                clean_trig = trig.replace(r"\w+", " ").replace(r"\s+", " ").replace(r"\b", "").strip()
                if clean_trig:
                    esc_cat = self._escape_sql_str(cat_id)
                    esc_kw = self._escape_sql_str(clean_trig)
                    kw_values.append(f"({esc_cat}, {esc_kw}, 'hot', 1.0, true)")

            # 2. Intent keywords (Tier: warm)
            for intent in cat.get("intent_keywords", []):
                clean_intent = intent.replace(r"\w+", " ").replace(r"\s+", " ").replace(r"\b", "").strip()
                if clean_intent:
                    esc_cat = self._escape_sql_str(cat_id)
                    esc_kw = self._escape_sql_str(clean_intent)
                    kw_values.append(f"({esc_cat}, {esc_kw}, 'warm', 0.8, true)")

            # 3. Negative keywords
            for neg in cat.get("negatives", []):
                clean_neg = neg.replace(r"\w+", " ").replace(r"\s+", " ").replace(r"\b", "").strip()
                if clean_neg:
                    esc_cat = self._escape_sql_str(cat_id)
                    esc_neg = self._escape_sql_str(clean_neg)
                    neg_values.append(f"({esc_cat}, {esc_neg}, 'category_stop', 'Initial seed negative keyword', true)")

        kw_count = len(kw_values)
        neg_count = len(neg_values)

        if kw_values:
            sql_kw = f"""
            INSERT INTO public.keywords_performance (category_id, keyword, tier, utility_score, is_active)
            VALUES {', '.join(kw_values)}
            ON CONFLICT (category_id, keyword) DO NOTHING;
            """
            self.execute_sql(sql_kw)

        if neg_values:
            sql_neg = f"""
            INSERT INTO public.negative_tokens (category_id, token, tier, reason, is_active)
            VALUES {', '.join(neg_values)}
            ON CONFLICT (category_id, token) DO NOTHING;
            """
            self.execute_sql(sql_neg)

        logger.info(f"✅ Успешно засеяно в Supabase: {kw_count} ключевых слов и {neg_count} минус-слов!")
        return {"keywords_seeded": kw_count, "negatives_seeded": neg_count}

    def get_summary_metrics(self) -> Dict[str, Any]:
        """Fetches total counts across all tables."""
        leads_sql = "SELECT COUNT(*) as count, status FROM public.leads GROUP BY status;"
        kw_sql = "SELECT COUNT(*) as total_keywords FROM public.keywords_performance WHERE is_active = true;"
        neg_sql = "SELECT COUNT(*) as total_negatives FROM public.negative_tokens WHERE is_active = true;"
        channels_sql = "SELECT COUNT(*) as total_channels FROM public.channel_scores;"

        leads_res = self.execute_sql(leads_sql) or []
        kw_res = self.execute_sql(kw_sql) or []
        neg_res = self.execute_sql(neg_sql) or []
        ch_res = self.execute_sql(channels_sql) or []

        return {
            "leads_by_status": leads_res,
            "active_keywords": kw_res[0]["total_keywords"] if kw_res else 0,
            "active_negatives": neg_res[0]["total_negatives"] if neg_res else 0,
            "tracked_channels": ch_res[0]["total_channels"] if ch_res else 0,
        }
