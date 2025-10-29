"""
消息分析器模块
负责主动消息的消息历史获取和LLM调用分析
"""
import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from astrbot.core.message.components import Plain
from astrbot.core.message.message_event_result import MessageChain
from astrbot.api.provider import LLMResponse
from astrbot.core.star.exceptions import StarException


class MessageAnalyzer:
    """消息分析器"""

    def __init__(self, context, config: dict):
        self.context = context
        self.config = config
        self.logger = logging.getLogger(__name__)

        # 配置项
        self.no_message_threshold = self._parse_time_threshold(config.get("no_message_threshold", "30min"))
        self.enable_time_check = config.get("enable_time_check", True)

        # 引入提示词管理器
        from .prompt_manager import PromptManager
        self.prompt_manager = PromptManager(config)

    async def should_send_proactive_message(self, session_id: str) -> bool:
        """第一步：判断是否应该发送主动消息"""
        try:
            # 检查最近是否有消息
            has_recent_message = await self._has_recent_message(session_id)
            if has_recent_message:
                self.logger.debug(f"会话 {session_id} 最近有消息，跳过主动消息检查")
                return False

            # 构建分析提示词
            prompt = await self._build_analysis_prompt(session_id)

            # 调用LLM判断
            should_send = await self._call_llm_for_decision(prompt)

            self.logger.info(f"会话 {session_id} LLM决策结果: {'发送主动消息' if should_send else '不发送主动消息'}")
            return should_send

        except Exception as e:
            self.logger.error(f"判断是否发送主动消息时出现错误: {e}")
            return False

    async def get_proactive_topic(self, session_id: str) -> Optional[str]:
        """第二步：生成主动消息话题（仅在第一步返回YES时调用）"""
        try:
            # 构建话题生成提示词
            prompt = await self._build_topic_prompt(session_id)

            # 调用LLM生成话题
            topic = await self._call_llm_for_topic(prompt)

            if topic:
                self.logger.info(f"为会话 {session_id} 生成话题: {topic}")
            else:
                self.logger.warning(f"会话 {session_id} 未能生成话题")

            return topic

        except Exception as e:
            self.logger.error(f"生成主动消息话题时出现错误: {e}")
            return None

    async def _has_recent_message(self, session_id: str) -> bool:
        """检查会话是否有最近的消息"""
        try:
            # 获取会话的最后一条消息时间
            last_message_time = await self._get_last_message_time(session_id)

            if not last_message_time:
                return False

            # 计算时间差
            current_time = datetime.now()
            time_diff = current_time - last_message_time

            # 检查是否超过阈值
            return time_diff < timedelta(seconds=self.no_message_threshold)

        except Exception as e:
            self.logger.error(f"检查最近消息失败: {e}")
            return False

    async def _get_last_message_time(self, session_id: str) -> Optional[datetime]:
        """获取会话最后一条消息的时间"""
        try:
            # 尝试从消息存储中获取最后一条消息的时间
            if hasattr(self.context, 'message_manager'):
                message_manager = self.context.message_manager
                last_message = await message_manager.get_last_message(session_id)
                if last_message and hasattr(last_message, 'timestamp'):
                    return last_message.timestamp

            # 如果没有消息管理器或获取失败，返回None
            return None

        except Exception as e:
            self.logger.error(f"获取最后消息时间失败: {e}")
            return None

    async def _get_message_history(self, session_id: str) -> List[Dict[str, Any]]:
        """获取消息历史"""
        try:
            # 尝试从消息存储中获取历史消息
            if hasattr(self.context, 'message_manager'):
                message_manager = self.context.message_manager
                messages = await message_manager.get_message_history(session_id, limit=10)

                # 转换为标准格式
                history = []
                for msg in messages:
                    history.append({
                        'role': 'user' if hasattr(msg, 'is_user') and msg.is_user else 'bot',
                        'content': getattr(msg, 'content', ''),
                        'timestamp': getattr(msg, 'timestamp', None)
                    })
                return history

            # 如果没有消息管理器，返回空列表
            return []

        except Exception as e:
            self.logger.error(f"获取消息历史失败: {e}")
            return []

    async def _build_analysis_prompt(self, session_id: str) -> str:
        """构建分析提示词"""
        message_history = await self._get_message_history(session_id)

        # 构建上下文
        dialogue_history = "对话历史:\n"
        for i, msg in enumerate(message_history[-5:]):  # 只取最近5条消息
            dialogue_history += f"{i+1}. {msg.get('role', 'unknown')}: {msg.get('content', 'empty')}\n"

        # 获取回复频率模式描述
        frequency_mode = self.config.get("reply_frequency", "moderate")
        frequency_descriptions = {
            "rare": "稀少模式 - 平均8小时回复，误差正负5小时",
            "moderate": "适中模式 - 平均4小时回复，误差正负3小时",
            "frequent": "频繁模式 - 平均1小时回复，误差正负半小时"
        }

        # 使用提示词管理器生成提示词
        time_info = '已启用时间感知' if self.enable_time_check else '未启用时间感知'
        frequency_info = frequency_descriptions.get(frequency_mode, frequency_descriptions['moderate'])

        return self.prompt_manager.get_analysis_prompt(
            dialogue_history,
            time_info,
            frequency_info
        )

    async def _build_topic_prompt(self, session_id: str) -> str:
        """构建话题生成提示词"""
        message_history = await self._get_message_history(session_id)

        # 构建上下文
        dialogue_history = "对话历史:\n"
        for i, msg in enumerate(message_history[-5:]):  # 只取最近5条消息
            dialogue_history += f"{i+1}. {msg.get('role', 'unknown')}: {msg.get('content', 'empty')}\n"

        # 使用提示词管理器生成提示词
        return self.prompt_manager.get_topic_prompt(dialogue_history)

    async def _call_llm_for_decision(self, prompt: str) -> bool:
        """调用LLM进行决策"""
        try:
            # 检查是否有LLM提供者
            if not hasattr(self.context, 'provider_manager') or not self.context.provider_manager:
                self.logger.error("没有可用的LLM提供者")
                return False

            # 获取LLM提供者
            llm_provider = self.context.provider_manager.get_llm_provider()
            if not llm_provider:
                self.logger.error("没有可用的LLM提供者")
                return False

            # 构建消息
            messages = [
                {"role": "system", "content": "你是一个智能对话分析助手，负责判断是否适合发送主动消息。"},
                {"role": "user", "content": prompt}
            ]

            # 调用LLM
            response = await llm_provider.generate(messages)
            if not response or not response.completion_text:
                self.logger.error("LLM响应为空")
                return False

            # 解析响应
            response_text = response.completion_text.strip()
            if "^&YES&^" in response_text:
                return True
            elif "^&NO&^" in response_text:
                return False
            else:
                self.logger.warning(f"LLM返回了无法识别的响应: {response_text}")
                return False

        except Exception as e:
            self.logger.error(f"调用LLM进行决策时出现错误: {e}")
            return False

    async def _call_llm_for_topic(self, prompt: str) -> Optional[str]:
        """调用LLM生成话题"""
        try:
            # 检查是否有LLM提供者
            if not hasattr(self.context, 'provider_manager') or not self.context.provider_manager:
                self.logger.error("没有可用的LLM提供者")
                return None

            # 获取LLM提供者
            llm_provider = self.context.provider_manager.get_llm_provider()
            if not llm_provider:
                self.logger.error("没有可用的LLM提供者")
                return None

            # 构建消息
            messages = [
                {"role": "system", "content": "你是一个智能话题生成助手，负责生成自然的对话话题。"},
                {"role": "user", "content": prompt}
            ]

            # 调用LLM
            response = await llm_provider.generate(messages)
            if not response or not response.completion_text:
                self.logger.error("LLM响应为空")
                return None

            # 提取话题内容
            response_text = response.completion_text.strip()
            return response_text

        except Exception as e:
            self.logger.error(f"调用LLM生成话题时出现错误: {e}")
            return None

    def _parse_time_threshold(self, threshold: str) -> int:
        """解析时间阈值为秒数"""
        threshold_mapping = {
            '1min': 60,
            '5min': 5 * 60,
            '10min': 10 * 60,
            '30min': 30 * 60,
            '1hour': 60 * 60
        }

        return threshold_mapping.get(threshold, 30 * 60)  # 默认30分钟