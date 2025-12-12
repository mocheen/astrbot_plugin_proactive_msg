"""
消息分析器模块
负责主动消息的消息历史获取和LLM调用分析
"""
import asyncio
import time
import zoneinfo
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any

from astrbot.core.message.components import Plain
from astrbot.core.message.message_event_result import MessageChain
from astrbot.api.provider import LLMResponse
from astrbot.api import logger
from .message_history_enhancer import MessageHistoryEnhancer


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
        self.enable_timestamp_enhancement = config.get("enable_timestamp_enhancement", True)

        # 引入提示词管理器
        from .prompt_manager import PromptManager
        self.prompt_manager = PromptManager(config)

        # 初始化消息历史增强器
        self.history_enhancer = MessageHistoryEnhancer(context)

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

            # 构建话题提示词（使用已有的消息历史，避免重复获取）
            prompt = self._build_topic_prompt_with_history(dialogue_history)

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
            last_message_timestamp = await self._get_last_message_time(session_id)

            if not last_message_timestamp:
                return False

            # 计算时间差
            current_timestamp = int(time.time())
            time_diff = current_timestamp - last_message_timestamp

            # 检查是否超过阈值
            return time_diff < self.no_message_threshold

        except Exception as e:
            self.logger.error(f"检查最近消息失败: {e}")
            return False

    async def _get_last_message_time(self, session_id: str) -> Optional[int]:
        """获取会话的最后一条消息时间戳"""
        try:
            # 验证 session_id 参数类型
            if not session_id:
                self.logger.warning("session_id 为空")
                return None

            if isinstance(session_id, list):
                self.logger.error(f"session_id 不能是列表类型: {session_id}")
                return None

            if not isinstance(session_id, str):
                self.logger.error(f"session_id 必须是字符串类型，当前类型: {type(session_id)}, 值: {session_id}")
                return None

            # 首先尝试通过 conversation_manager 获取会话历史
            conversation_manager = self.context.conversation_manager
            if not conversation_manager:
                self.logger.error("无法获取 conversation_manager")
                return None

            # 获取当前会话ID
            conversation_id = await conversation_manager.get_curr_conversation_id(session_id)
            if not conversation_id:
                self.logger.warning(f"会话 {session_id} 没有对应的对话ID")
                return None

            # 获取会话历史
            conversation = await conversation_manager.get_conversation(session_id, conversation_id)
            if not conversation:
                self.logger.warning(f"未找到会话 {session_id}")
                return None

            # 检查会话是否有历史记录
            if hasattr(conversation, 'history') and conversation.history:
                try:
                    # 尝试解析历史记录
                    import json
                    history_data = json.loads(conversation.history) if isinstance(conversation.history, str) else conversation.history
                    
                    if history_data and len(history_data) > 0:
                        # 获取最后一条消息
                        last_message = history_data[-1]
                        
                        # 检查是否有时间戳
                        if 'timestamp' in last_message:
                            timestamp = last_message['timestamp']
                            self.logger.debug(f"从会话历史获取到时间戳: {timestamp}")
                            return int(timestamp)
                        
                        # 如果没有时间戳，尝试从其他字段获取
                        if 'time' in last_message:
                            timestamp = last_message['time']
                            self.logger.debug(f"从会话历史获取到时间戳(time字段): {timestamp}")
                            return int(timestamp)
                            
                except (json.JSONDecodeError, ValueError, TypeError) as e:
                    self.logger.error(f"解析会话历史失败: {e}")
            
            # 如果会话历史中没有时间戳，尝试使用会话的更新时间
            if hasattr(conversation, 'updated_at') and conversation.updated_at:
                self.logger.debug(f"使用会话的updated_at作为时间戳: {conversation.updated_at}")
                return int(conversation.updated_at)
            
            # 如果会话有created_at字段，也可以使用
            if hasattr(conversation, 'created_at') and conversation.created_at:
                self.logger.debug(f"使用会话的created_at作为时间戳: {conversation.created_at}")
                return int(conversation.created_at)
                
            # 尝试通过 platform_message_history_manager 获取
            try:
                platform_message_history_manager = self.context.message_history_manager
                if platform_message_history_manager:
                    # 获取该会话的最新消息
                    platform_id = session_id.split('_')[0] if '_' in session_id else session_id
                    user_id = session_id.split('_')[1] if '_' in session_id else 'default'
                    
                    history = await platform_message_history_manager.get_platform_message_history(platform_id, user_id, limit=1)
                    if history and len(history) > 0:
                        last_message = history[0]
                        if hasattr(last_message, 'created_at') and last_message.created_at:
                            self.logger.debug(f"从平台消息历史获取到时间戳: {last_message.created_at}")
                            return int(last_message.created_at)
            except Exception as e:
                self.logger.error(f"从平台消息历史获取时间戳失败: {e}")
            
            self.logger.warning("无法获取最后一条消息的时间戳")
            return None
            
        except Exception as e:
            self.logger.error(f"获取最后一条消息时间时出错: {e}")
            return None

    async def _get_message_history(self, session_id: str) -> List[Dict[str, Any]]:
        """获取消息历史"""
        try:
            # 验证 session_id 参数类型
            if not session_id:
                self.logger.warning("session_id 为空")
                return []

            if isinstance(session_id, list):
                self.logger.error(f"session_id 不能是列表类型: {session_id}")
                return []

            if not isinstance(session_id, str):
                self.logger.error(f"session_id 必须是字符串类型，当前类型: {type(session_id)}, 值: {session_id}")
                return []

            self.logger.debug(f"尝试获取会话 {session_id} 的消息历史")

            if self.enable_timestamp_enhancement:
                # 使用增强器获取带时间戳的消息历史
                enhanced_history = await self.history_enhancer.get_enhanced_conversation_history(session_id, limit=10)
                if enhanced_history:
                    self.logger.debug(f"使用增强器获取到 {len(enhanced_history)} 条带时间戳的消息")
                    return enhanced_history

            # 回退到原始方法
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
            # 添加时间信息（如果存在）
            timestamp_str = ""
            if 'timestamp' in msg:
                timestamp_str = f" [{self.history_enhancer.format_timestamp(msg['timestamp'])}]"

            dialogue_history += f"{i+1}. {msg.get('role', 'unknown')}{timestamp_str}: {msg.get('content', 'empty')}\n"

        # 获取回复频率模式描述
        frequency_mode = self.config.get("reply_frequency", "moderate")
        frequency_descriptions = {
            "rare": "稀少模式 - 平均8小时发送，误差正负5小时",
            "moderate": "适中模式 - 平均4小时发送，误差正负3小时",
            "frequent": "频繁模式 - 平均1小时发送，误差正负半小时"
        }

        # 使用提示词管理器生成用户提示词
        if self.enable_time_check:
            if self.enable_timestamp_enhancement:
                # 使用增强器的时区感知功能
                current_time = self.history_enhancer.get_current_time()
                time_str = self.history_enhancer.format_timestamp_with_timezone(int(current_time.timestamp()))
                period_str = self.history_enhancer.get_time_period_description(current_time)
                time_info = f'当前时间: {time_str} ({period_str})'
            else:
                # 使用AstrBot的时区处理方式
                cfg = self.context.get_config()
                timezone_str = cfg.get("timezone")

                if timezone_str:
                    try:
                        current_time = datetime.now(zoneinfo.ZoneInfo(timezone_str))
                    except Exception as e:
                        logger.error(f"时区设置错误: {e}, 回退到本地时区")
                        current_time = datetime.now().astimezone()
                else:
                    current_time = datetime.now().astimezone()

                time_info = f'当前时间: {current_time.strftime("%Y-%m-%d %H:%M:%S")} ({self._get_time_period(current_time)})'
        else:
            time_info = '未启用时间感知'
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
            # 添加时间信息（如果存在）
            timestamp_str = ""
            if 'timestamp' in msg:
                timestamp_str = f" [{self.history_enhancer.format_timestamp(msg['timestamp'])}]"

            dialogue_history += f"{i+1}. {msg.get('role', 'unknown')}{timestamp_str}: {msg.get('content', 'empty')}\n"

        # 使用提示词管理器生成用户提示词
        return self.prompt_manager.get_topic_prompt(dialogue_history)

    def _build_topic_prompt_with_history(self, dialogue_history_list: List[Dict[str, Any]]) -> str:
        """构建话题生成用户提示词（使用已有的消息历史）"""
        # 构建上下文
        dialogue_history = "对话历史:\n"
        for i, msg in enumerate(dialogue_history_list[-5:]):  # 只取最近5条消息
            # 添加时间信息（如果存在）
            timestamp_str = ""
            if 'timestamp' in msg:
                timestamp_str = f" [{self.history_enhancer.format_timestamp(msg['timestamp'])}]"

            dialogue_history += f"{i+1}. {msg.get('role', 'unknown')}{timestamp_str}: {msg.get('content', 'empty')}\n"

        # 使用提示词管理器生成用户提示词
        return self.prompt_manager.get_topic_prompt(dialogue_history)

    async def _call_llm_for_decision(self, prompt: str) -> tuple[bool, str]:
        """调用LLM进行决策"""
        try:
            
            # 获取LLM提供者 - 使用AstrBot核心系统的方式
            provider = self.context.get_using_provider()
            if not provider:
                self.logger.warning("没有可用的LLM提供者，可能是系统尚未完全初始化")
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

        except asyncio.CancelledError:
            self.logger.warning("LLM调用被取消，可能是系统初始化过程中的正常情况")
            return False, "LLM调用被取消"
        except Exception as e:
            self.logger.error(f"调用LLM进行决策时出现错误: {e}")
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

    def _get_time_period(self, dt: datetime) -> str:
        """获取时间段描述"""
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