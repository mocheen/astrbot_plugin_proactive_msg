"""
消息历史时间戳增强器
在不修改AstrBot本体代码的前提下，为消息历史添加时间戳信息
"""
import time
import json
import zoneinfo
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from astrbot.api import logger


class MessageHistoryEnhancer:
    """消息历史增强器，负责为消息历史添加时间戳信息"""

    def __init__(self, context):
        """初始化消息历史增强器"""
        self.context = context
        self.db = context.get_db()
        self.conversation_manager = context.conversation_manager

    def get_current_time(self) -> datetime:
        """获取当前时间（使用AstrBot的时区配置）"""
        try:
            cfg = self.context.get_config()
            timezone_str = cfg.get("timezone")

            if timezone_str:
                try:
                    # 使用配置的时区
                    return datetime.now(zoneinfo.ZoneInfo(timezone_str))
                except Exception as e:
                    logger.error(f"时区设置错误: {e}, 回退到本地时区")

            # 回退到本地时区
            return datetime.now().astimezone()
        except Exception as e:
            logger.error(f"获取当前时间失败: {e}")
            return datetime.now().astimezone()

    def format_timestamp_with_timezone(self, timestamp: Any) -> str:
        """根据配置的时区格式化时间戳"""
        if not timestamp:
            return ""

        try:
            # 获取配置的时区
            cfg = self.context.get_config()
            timezone_str = cfg.get("timezone")

            if isinstance(timestamp, (int, float)):
                # 首先创建UTC时间
                dt_utc = datetime.fromtimestamp(timestamp, tz=timezone.utc)

                if timezone_str:
                    # 转换到配置的时区
                    dt_local = dt_utc.astimezone(zoneinfo.ZoneInfo(timezone_str))
                else:
                    # 使用本地时区
                    dt_local = dt_utc.astimezone()

                return dt_local.strftime("%Y-%m-%d %H:%M:%S")

            elif isinstance(timestamp, str):
                # 尝试解析字符串时间戳
                try:
                    dt_utc = datetime.fromtimestamp(float(timestamp), tz=timezone.utc)

                    if timezone_str:
                        dt_local = dt_utc.astimezone(zoneinfo.ZoneInfo(timezone_str))
                    else:
                        dt_local = dt_utc.astimezone()

                    return dt_local.strftime("%Y-%m-%d %H:%M:%S")
                except ValueError:
                    return timestamp
            else:
                return str(timestamp)
        except Exception as e:
            logger.warning(f"格式化时间戳失败: {e}")
            return str(timestamp)

    async def enhance_message_history(self, conversation_id: str) -> List[Dict[str, Any]]:
        """为指定对话的历史消息添加时间戳

        Args:
            conversation_id: 对话ID

        Returns:
            增强后的消息历史列表，每条消息包含timestamp字段
        """
        try:
            # 获取原始对话数据
            conversation = await self.conversation_manager.get_conversation("", conversation_id)
            if not conversation or not conversation.history:
                return []

            # 解析历史消息
            if isinstance(conversation.history, str):
                history_data = json.loads(conversation.history)
            else:
                history_data = conversation.history

            # 增强每条消息
            enhanced_history = []
            for msg in history_data:
                enhanced_msg = await self._enhance_single_message(msg)
                enhanced_history.append(enhanced_msg)

            # 如果有消息缺少时间戳，更新整个对话历史
            if self._needs_timestamp_update(history_data, enhanced_history):
                await self._update_conversation_history(conversation_id, enhanced_history)

            return enhanced_history

        except Exception as e:
            logger.error(f"增强消息历史失败: {e}")
            return []

    async def _enhance_single_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """为单条消息添加时间戳"""
        enhanced_msg = message.copy()

        # 如果消息已经有时间戳，直接返回
        if 'timestamp' in message:
            return enhanced_msg

        # 根据消息内容估算时间戳
        # 这是一个简化的策略，实际使用时可以根据需要调整
        enhanced_msg['timestamp'] = int(time.time())

        return enhanced_msg

    def _needs_timestamp_update(self, original: List[Dict], enhanced: List[Dict]) -> bool:
        """检查是否需要更新对话历史"""
        for orig_msg, enhanced_msg in zip(original, enhanced):
            if orig_msg.get('timestamp') != enhanced_msg.get('timestamp'):
                return True
        return False

    async def _update_conversation_history(self, conversation_id: str, enhanced_history: List[Dict]) -> bool:
        """更新对话历史到数据库"""
        try:
            await self.db.update_conversation(
                cid=conversation_id,
                content=enhanced_history
            )
            logger.info(f"已更新对话 {conversation_id} 的历史消息时间戳")
            return True
        except Exception as e:
            logger.error(f"更新对话历史失败: {e}")
            return False

    async def add_message_with_timestamp(
        self,
        conversation_id: str,
        role: str,
        content: str,
        timestamp: Optional[int] = None
    ) -> bool:
        """添加带时间戳的新消息到对话历史

        Args:
            conversation_id: 对话ID
            role: 消息角色 (user/assistant)
            content: 消息内容
            timestamp: 时间戳，如果为None则使用当前时间

        Returns:
            是否成功添加
        """
        try:
            # 获取当前对话
            conversation = await self.conversation_manager.get_conversation("", conversation_id)
            if not conversation:
                logger.warning(f"对话 {conversation_id} 不存在")
                return False

            # 解析当前历史
            if isinstance(conversation.history, str):
                history = json.loads(conversation.history)
            else:
                history = conversation.history or []

            # 创建新消息
            new_message = {
                'role': role,
                'content': content,
                'timestamp': timestamp or int(time.time())
            }

            # 添加到历史
            history.append(new_message)

            # 更新对话
            await self.db.update_conversation(
                cid=conversation_id,
                content=history
            )

            logger.debug(f"已添加新消息到对话 {conversation_id}: {role} - {content[:50]}...")
            return True

        except Exception as e:
            logger.error(f"添加消息到对话历史失败: {e}")
            return False

    def format_timestamp(self, timestamp: Any) -> str:
        """格式化时间戳为可读字符串（考虑时区）"""
        return self.format_timestamp_with_timezone(timestamp)

    def get_time_period_description(self, dt: datetime) -> str:
        """获取时间段描述（考虑时区）"""
        # 如果是naive datetime（无时区信息），转换为本地时区
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.now().astimezone().tzinfo)

        hour = dt.hour

        if 5 <= hour < 8:
            return "清晨"
        elif 8 <= hour < 12:
            return "上午"
        elif 12 <= hour < 14:
            return "中午"
        elif 14 <= hour < 17:
            return "下午"
        elif 17 <= hour < 19:
            return "傍晚"
        elif 19 <= hour < 22:
            return "晚上"
        elif 22 <= hour or hour < 2:
            return "深夜"
        else:  # 2 <= hour < 5
            return "凌晨"

    async def get_enhanced_conversation_history(
        self,
        session_id: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """获取增强的对话历史

        Args:
            session_id: 会话ID
            limit: 获取消息数量限制

        Returns:
            增强的对话历史列表
        """
        try:
            # 获取当前对话ID
            conversation_id = await self.conversation_manager.get_curr_conversation_id(session_id)
            if not conversation_id:
                logger.warning(f"会话 {session_id} 没有当前对话")
                return []

            # 获取增强的历史消息
            enhanced_history = await self.enhance_message_history(conversation_id)

            # 返回最近的消息
            return enhanced_history[-limit:] if enhanced_history else []

        except Exception as e:
            logger.error(f"获取增强对话历史失败: {e}")
            return []

    async def estimate_message_time(self, conversation_id: str, message_index: int) -> Optional[int]:
        """估算消息的发送时间

        Args:
            conversation_id: 对话ID
            message_index: 消息在历史中的索引

        Returns:
            估算的时间戳
        """
        try:
            conversation = await self.conversation_manager.get_conversation("", conversation_id)
            if not conversation or not conversation.created_at:
                return None

            # 使用对话创建时间作为基准
            base_time = conversation.created_at
            if isinstance(base_time, str):
                # 如果是字符串，尝试解析
                try:
                    # 简单的时间格式解析
                    if 'T' in base_time:
                        dt = datetime.fromisoformat(base_time.replace('Z', '+00:00'))
                    else:
                        dt = datetime.fromisoformat(base_time)
                    base_time = int(dt.timestamp())
                except:
                    base_time = int(time.time())
            elif isinstance(base_time, datetime):
                base_time = int(base_time.timestamp())
            else:
                base_time = int(time.time())

            # 简单估算：假设消息均匀分布
            # 这只是一个粗略的估算，可以根据需要改进
            current_time = int(time.time())
            total_duration = current_time - base_time

            if total_duration <= 0:
                return current_time

            # 根据消息索引估算时间
            estimated_time = base_time + (total_duration * message_index // max(1, len(conversation.history) or 1))

            return estimated_time

        except Exception as e:
            logger.error(f"估算消息时间失败: {e}")
            return None