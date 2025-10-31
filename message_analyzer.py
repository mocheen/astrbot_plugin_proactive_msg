"""
消息分析器模块
负责主动消息的消息历史获取和LLM调用分析
"""
import asyncio
import time
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from astrbot.core.message.components import Plain
from astrbot.core.message.message_event_result import MessageChain
from astrbot.api.provider import LLMResponse
from astrbot.api import logger


class MessageAnalyzer:
    """消息分析器"""

    def __init__(self, context, config: dict):
        self.context = context
        self.config = config
        # 使用AstrBot提供的logger
        self.logger = logger

        # 配置项
        self.no_message_threshold = self._parse_time_threshold(config.get("no_message_threshold", "30min"))
        self.enable_time_check = config.get("enable_time_check", True)

        # 引入提示词管理器
        from .prompt_manager import PromptManager
        self.prompt_manager = PromptManager(config)

    async def should_send_proactive_message(self, session_id: str) -> bool:
        """第一步：判断是否应该发送主动消息"""
        try:
            self.logger.info(f"开始分析会话 {session_id} 是否需要发送主动消息")
            
            # 检查最近是否有消息
            has_recent_message = await self._has_recent_message(session_id)
            if has_recent_message:
                self.logger.info(f"会话 {session_id} 最近有消息，跳过主动消息检查")
                return False

            # 获取消息历史
            message_history = await self._get_message_history(session_id)
            if not message_history:
                self.logger.warning(f"会话 {session_id} 没有消息历史，无法进行LLM分析")
                return False
                
            self.logger.info(f"会话 {session_id} 获取到 {len(message_history)} 条消息历史")

            # 构建分析提示词
            prompt = await self._build_analysis_prompt(session_id)
            self.logger.debug(f"会话 {session_id} 构建的分析提示词长度: {len(prompt)} 字符")

            # 调用LLM判断
            should_send, llm_response = await self._call_llm_for_decision(prompt)

            # 记录详细的决策结果
            decision = "发送主动消息" if should_send else "不发送主动消息"
            self.logger.info(f"会话 {session_id} LLM决策结果: {decision}")
            self.logger.info(f"会话 {session_id} LLM完整回复: {llm_response}")
            
            return should_send

        except Exception as e:
            self.logger.error(f"判断是否发送主动消息时出现错误: {e}")
            return False

    async def get_proactive_topic(self, session_id: str) -> Optional[str]:
        """第二步：生成主动消息话题（仅在第一步返回YES时调用）"""
        try:
            # 获取消息历史
            dialogue_history = await self._get_message_history(session_id)
            if not dialogue_history:
                self.logger.warning(f"会话 {session_id} 没有消息历史，无法生成话题")
                return None

            # 构建话题提示词
            prompt = await self._build_topic_prompt(dialogue_history)

            # 调用LLM生成话题
            topic = await self._call_llm_for_topic(prompt)
            
            if topic:
                self.logger.info(f"会话 {session_id} 生成话题: {topic}")
            else:
                self.logger.warning(f"会话 {session_id} 生成话题失败")
            
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
            self.logger.debug(f"尝试获取会话 {session_id} 的最后消息时间")
            
            # 尝试从消息存储中获取最后一条消息的时间
            if hasattr(self.context, 'message_manager'):
                message_manager = self.context.message_manager
                last_message = await message_manager.get_last_message(session_id)
                if last_message and hasattr(last_message, 'timestamp'):
                    self.logger.debug(f"会话 {session_id} 最后消息时间: {last_message.timestamp}")
                    return last_message.timestamp
                else:
                    self.logger.debug(f"会话 {session_id} 没有最后消息或消息没有时间戳")
            else:
                self.logger.warning(f"上下文中没有message_manager属性")
                
            # 尝试使用conversation_manager
            if hasattr(self.context, 'conversation_manager'):
                conversation_manager = self.context.conversation_manager
                conversations = await conversation_manager.get_conversations()
                
                # 查找匹配的会话
                for conv in conversations:
                    if conv.user_id == session_id:
                        # 获取该会话的消息
                        if hasattr(conv, 'get_messages'):
                            messages = await conv.get_messages(limit=1)
                            if messages and len(messages) > 0:
                                last_message = messages[0]
                                if hasattr(last_message, 'timestamp'):
                                    self.logger.debug(f"会话 {session_id} 最后消息时间(从conversation获取): {last_message.timestamp}")
                                    return last_message.timestamp
                                else:
                                    self.logger.debug(f"会话 {session_id} 最后消息没有时间戳")
                            else:
                                self.logger.debug(f"会话 {session_id} 没有消息")
                        break
            else:
                self.logger.warning(f"上下文中没有conversation_manager属性")

            # 如果没有消息管理器或获取失败，返回None
            self.logger.warning(f"无法获取会话 {session_id} 的最后消息时间")
            return None

        except Exception as e:
            self.logger.error(f"获取最后消息时间失败: {e}")
            return None

    async def _get_message_history(self, session_id: str) -> List[Dict[str, Any]]:
        """获取消息历史"""
        try:
            self.logger.debug(f"尝试获取会话 {session_id} 的消息历史")
            
            # 使用AstrBot核心系统的方式获取对话历史
            conversation_manager = self.context.conversation_manager
            
            # 获取当前会话ID
            conversation_id = await conversation_manager.get_curr_conversation_id(session_id)
            if not conversation_id:
                self.logger.warning(f"会话 {session_id} 没有对应的对话ID")
                return []
                
            # 获取对话对象
            conversation = await conversation_manager.get_conversation(session_id, conversation_id)
            if not conversation:
                self.logger.warning(f"无法获取会话 {session_id} 的对话对象")
                return []
                
            # 解析对话历史
            history_json = conversation.history
            if not history_json:
                self.logger.warning(f"会话 {session_id} 的对话历史为空")
                return []
                
            # 解析JSON格式的对话历史
            import json
            try:
                history_data = json.loads(history_json)
                self.logger.debug(f"从conversation获取到 {len(history_data) if history_data else 0} 条消息")
                return history_data
            except json.JSONDecodeError as e:
                self.logger.error(f"解析对话历史JSON失败: {e}")
                return []

        except Exception as e:
            self.logger.error(f"获取消息历史失败: {e}")
            return []

    async def _build_analysis_prompt(self, session_id: str) -> str:
        """构建分析用户提示词"""
        message_history = await self._get_message_history(session_id)

        # 构建上下文
        dialogue_history = "对话历史:\n"
        for i, msg in enumerate(message_history[-5:]):  # 只取最近5条消息
            dialogue_history += f"{i+1}. {msg.get('role', 'unknown')}: {msg.get('content', 'empty')}\n"

        # 获取回复频率模式描述
        frequency_mode = self.config.get("reply_frequency", "moderate")
        frequency_descriptions = {
            "rare": "稀少模式 - 平均8小时发送，误差正负5小时",
            "moderate": "适中模式 - 平均4小时发送，误差正负3小时",
            "frequent": "频繁模式 - 平均1小时发送，误差正负半小时"
        }

        # 使用提示词管理器生成用户提示词
        time_info = '已启用时间感知' if self.enable_time_check else '未启用时间感知'
        frequency_info = frequency_descriptions.get(frequency_mode, frequency_descriptions['moderate'])

        return self.prompt_manager.get_analysis_prompt(
            dialogue_history,
            time_info,
            frequency_info
        )

    async def _build_topic_prompt(self, session_id: str) -> str:
        """构建话题生成用户提示词"""
        message_history = await self._get_message_history(session_id)

        # 构建上下文
        dialogue_history = "对话历史:\n"
        for i, msg in enumerate(message_history[-5:]):  # 只取最近5条消息
            dialogue_history += f"{i+1}. {msg.get('role', 'unknown')}: {msg.get('content', 'empty')}\n"

        # 使用提示词管理器生成用户提示词
        return self.prompt_manager.get_topic_prompt(dialogue_history)

    async def _call_llm_for_decision(self, prompt: str) -> tuple[bool, str]:
        """调用LLM进行决策"""
        try:
            self.logger.info("开始调用LLM进行决策")
            
            # 获取LLM提供者 - 使用AstrBot核心系统的方式
            provider = self.context.get_using_provider()
            if not provider:
                self.logger.info("没有可用的LLM提供者")
                return False, "没有可用的LLM提供者"

            self.logger.info(f"成功获取LLM提供者: {provider.meta().id}")
            
            # 使用提示词管理器获取系统提示词
            system_prompt = self.prompt_manager.get_analysis_system_prompt()
            
            # 记录给LLM的整体信息
            self.logger.info(f"LLM决策请求 - 系统提示: {system_prompt}")
            self.logger.info(f"LLM决策请求 - 用户提示: {prompt} ")

            # 调用LLM - 使用AstrBot核心系统的方式
            response = await provider.text_chat(
                prompt=prompt,
                system_prompt=system_prompt
            )
            
            if not response:
                self.logger.info("LLM响应为None")
                return False, "LLM响应为None"
                
            if not response.completion_text:
                self.logger.info("LLM响应的completion_text为空")
                return False, "LLM响应的completion_text为空"

            # 记录LLM的回复
            response_text = response.completion_text.strip()
            self.logger.info(f"LLM决策回复: {response_text}")
            
            if "^&YES&^" in response_text:
                return True, response_text
            elif "^&NO&^" in response_text:
                return False, response_text
            else:
                self.logger.info(f"LLM返回了无法识别的响应: {response_text}")
                return False, response_text

        except Exception as e:
            self.logger.info(f"调用LLM进行决策时出现错误: {e}")
            return False, f"调用LLM时出现错误: {str(e)}"

    async def _call_llm_for_topic(self, prompt: str) -> Optional[str]:
        """调用LLM生成话题"""
        try:
            # 获取LLM提供者 - 使用AstrBot核心系统的方式
            provider = self.context.get_using_provider()
            if not provider:
                self.logger.info("没有可用的LLM提供者")
                return None

            # 使用提示词管理器获取系统提示词
            system_prompt = self.prompt_manager.get_topic_system_prompt()
            
            # 记录给LLM的整体信息
            self.logger.info(f"LLM话题生成请求 - 系统提示: {system_prompt}")
            self.logger.info(f"LLM话题生成请求 - 用户提示: {prompt} ")

            # 调用LLM - 使用AstrBot核心系统的方式
            response = await provider.text_chat(
                prompt=prompt,
                system_prompt=system_prompt
            )
            
            if not response or not response.completion_text:
                self.logger.info("LLM响应为空")
                return None

            # 记录LLM的回复
            response_text = response.completion_text.strip()
            self.logger.info(f"LLM话题生成回复: {response_text}")
            return response_text

        except Exception as e:
            self.logger.info(f"调用LLM生成话题时出现错误: {e}")
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