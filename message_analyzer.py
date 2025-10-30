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
            self.logger.info(f"开始分析会话 {session_id} 是否需要发送主动消息")

            # 检查最近是否有消息
            self.logger.info(f"检查会话 {session_id} 最近是否有消息")
            has_recent_message = await self._has_recent_message(session_id)
            if has_recent_message:
                self.logger.info(f"会话 {session_id} 最近有消息，跳过主动消息检查")
                return False
            else:
                self.logger.info(f" 会话 {session_id} 最近没有消息，继续LLM分析")

            # 获取消息历史
            self.logger.info(f" 获取会话 {session_id} 的消息历史")
            message_history = await self._get_message_history(session_id)
            if not message_history:
                self.logger.warning(f" 会话 {session_id} 没有消息历史，无法进行LLM分析")
                return False

            self.logger.info(f" 会话 {session_id} 获取到 {len(message_history)} 条消息历史")

            # 构建分析提示词
            self.logger.info(f" 构建会话 {session_id} 的分析提示词")
            prompt = await self._build_analysis_prompt(session_id)
            self.logger.info(f" 会话 {session_id} 分析提示词构建完成，长度: {len(prompt)} 字符")

            # 调用LLM判断
            self.logger.info(f"调用LLM分析会话 {session_id}")
            should_send, llm_response = await self._call_llm_for_decision(prompt)

            # 记录详细的决策结果
            decision = "发送主动消息" if should_send else "不发送主动消息"
            self.logger.info(f" 会话 {session_id} LLM决策结果: {decision}")
            self.logger.info(f"会话 {session_id} LLM完整回复: {llm_response}")

            return should_send

        except Exception as e:
            self.logger.error(f"❌ [STEP1] 判断是否发送主动消息时出现错误: {e}")
            import traceback
            self.logger.error(f"❌ [STEP1] 详细错误信息: {traceback.format_exc()}")
            return False

    async def get_proactive_topic(self, session_id: str) -> Optional[str]:
        """第二步：生成主动消息话题（仅在第一步返回YES时调用）"""
        try:
            self.logger.info(f"🚀 [STEP2] 开始为会话 {session_id} 生成主动话题")

            # 获取消息历史
            self.logger.info(f"📚 [STEP2] 获取会话 {session_id} 的消息历史用于生成话题")
            dialogue_history = await self._get_message_history(session_id)
            if not dialogue_history:
                self.logger.warning(f"⚠️ [STEP2] 会话 {session_id} 没有消息历史，无法生成话题")
                return None

            self.logger.info(f"✅ [STEP2] 会话 {session_id} 获取到 {len(dialogue_history)} 条消息历史用于生成话题")

            # 构建话题提示词
            self.logger.info(f"🔨 [STEP2] 构建会话 {session_id} 的话题提示词")
            prompt = await self._build_topic_prompt(session_id)
            self.logger.info(f"✅ [STEP2] 会话 {session_id} 话题提示词构建完成，长度: {len(prompt)} 字符")

            # 调用LLM生成话题
            self.logger.info(f"🤖 [STEP2] 调用LLM为会话 {session_id} 生成话题")
            topic = await self._call_llm_for_topic(prompt)

            if topic:
                self.logger.info(f"✅ [STEP2] 会话 {session_id} 成功生成话题: {topic}")
            else:
                self.logger.warning(f"❌ [STEP2] 会话 {session_id} 生成话题失败")

            return topic

        except Exception as e:
            self.logger.error(f"❌ [STEP2] 生成主动消息话题时出现错误: {e}")
            import traceback
            self.logger.error(f"❌ [STEP2] 详细错误信息: {traceback.format_exc()}")
            return None

    async def _has_recent_message(self, session_id: str) -> bool:
        """检查会话是否有最近的消息"""
        try:
            self.logger.info(f"🕐 [TIME_CHECK] 检查会话 {session_id} 最近消息时间")

            # 获取会话的最后一条消息时间
            last_message_time = await self._get_last_message_time(session_id)
            self.logger.info(f"📅 [TIME_CHECK] 会话 {session_id} 最后消息时间: {last_message_time}")

            if not last_message_time:
                self.logger.info(f"⚠️ [TIME_CHECK] 会话 {session_id} 没有最后消息时间记录")
                return False

            # 计算时间差
            current_time = datetime.now()
            time_diff = current_time - last_message_time
            threshold_seconds = self.no_message_threshold

            self.logger.info(f"⏰ [TIME_CHECK] 会话 {session_id} 时间差: {time_diff} (阈值: {threshold_seconds}秒)")

            # 检查是否超过阈值
            has_recent = time_diff < timedelta(seconds=threshold_seconds)
            if has_recent:
                self.logger.info(f"✅ [TIME_CHECK] 会话 {session_id} 有最近消息，跳过主动消息检查")
            else:
                self.logger.info(f"⏭️ [TIME_CHECK] 会话 {session_id} 没有最近消息，继续LLM分析")

            return has_recent

        except Exception as e:
            self.logger.error(f"❌ [TIME_CHECK] 检查最近消息失败: {e}")
            import traceback
            self.logger.error(f"❌ [TIME_CHECK] 详细错误信息: {traceback.format_exc()}")
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
            self.logger.info(f"开始获取会话 {session_id} 的消息历史")

            # 使用AstrBot核心系统的方式获取对话历史
            conversation_manager = self.context.conversation_manager
            self.logger.info(f"会话 {session_id} - 成功获取conversation_manager")

            # 获取当前会话ID
            conversation_id = await conversation_manager.get_curr_conversation_id(session_id)
            self.logger.info(f"会话 {session_id} - 当前对话ID: {conversation_id}")
            if not conversation_id:
                self.logger.warning(f"会话 {session_id} 没有对应的对话ID")
                return []

            # 获取对话对象
            conversation = await conversation_manager.get_conversation(session_id, conversation_id)
            if not conversation:
                self.logger.warning(f"无法获取会话 {session_id} 的对话对象")
                return []

            self.logger.info(f"会话 {session_id} - 成功获取对话对象")

            # 解析对话历史
            history_json = conversation.history
            self.logger.info(f"会话 {session_id} - 原始历史数据长度: {len(history_json) if history_json else 0} 字符")
            if not history_json:
                self.logger.warning(f"会话 {session_id} 的对话历史为空")
                return []

            # 解析JSON格式的对话历史
            import json
            try:
                history_data = json.loads(history_json)
                self.logger.info(f"会话 {session_id} - 解析得到 {len(history_data) if history_data else 0} 条历史消息")

                # 详细的调试信息
                if self.config.get("debug_show_full_prompt", True) and history_data:
                    self.logger.info(f"会话 {session_id} - 历史消息样例:")
                    for i, msg in enumerate(history_data[:3]):  # 只显示前3条
                        self.logger.info(f"  消息{i+1}: {msg}")

                return history_data
            except json.JSONDecodeError as e:
                self.logger.error(f"解析对话历史JSON失败: {e}")
                self.logger.error(f"会话 {session_id} - 原始数据: {history_json[:200]}...")  # 显示前200字符
                return []

        except Exception as e:
            self.logger.error(f"获取消息历史失败: {e}")
            import traceback
            self.logger.error(f"详细错误信息: {traceback.format_exc()}")
            return []

    async def _build_analysis_prompt(self, session_id: str) -> str:
        """构建分析提示词"""
        message_history = await self._get_message_history(session_id)

        # 获取当前时间信息
        from datetime import datetime
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.logger.info(f"会话 {session_id} - 当前时间: {current_time}")

        # 构建上下文 - 增强时间信息显示
        dialogue_history = "对话历史:\n"
        for i, msg in enumerate(message_history[-5:]):  # 只取最近5条消息
            role = msg.get('role', 'unknown')
            content = msg.get('content', 'empty')
            # 尝试获取时间戳信息
            timestamp = msg.get('timestamp', '')
            if timestamp:
                dialogue_history += f"{i+1}. [{timestamp}] {role}: {content}\n"
            else:
                dialogue_history += f"{i+1}. [时间未知] {role}: {content}\n"

        # 获取回复频率模式描述
        frequency_mode = self.config.get("reply_frequency", "moderate")
        frequency_descriptions = {
            "rare": "稀少模式 - 平均8小时发送，误差正负5小时",
            "moderate": "适中模式 - 平均4小时发送，误差正负3小时",
            "frequent": "频繁模式 - 平均1小时发送，误差正负半小时"
        }

        # 构建详细的时间信息
        time_info = f"当前时间: {current_time} ({'已启用时间感知' if self.enable_time_check else '未启用时间感知'})"
        frequency_info = frequency_descriptions.get(frequency_mode, frequency_descriptions['moderate'])

        self.logger.info(f"会话 {session_id} - 时间信息: {time_info}")
        self.logger.info(f"会话 {session_id} - 频率信息: {frequency_info}")

        prompt = self.prompt_manager.get_analysis_prompt(
            dialogue_history,
            time_info,
            frequency_info
        )

        # 根据配置决定是否记录完整的提示词内容用于调试
        if self.config.get("debug_show_full_prompt", True):
            self.logger.info(f"会话 {session_id} - 完整分析提示词:\n{prompt}")
        else:
            self.logger.info(f"会话 {session_id} - 提示词已生成（长度: {len(prompt)} 字符）")

        return prompt

    async def _build_topic_prompt(self, session_id: str) -> str:
        """构建话题生成提示词"""
        message_history = await self._get_message_history(session_id)

        # 构建上下文
        dialogue_history = "对话历史:\n"
        for i, msg in enumerate(message_history[-5:]):  # 只取最近5条消息
            dialogue_history += f"{i+1}. {msg.get('role', 'unknown')}: {msg.get('content', 'empty')}\n"

        # 使用提示词管理器生成提示词
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

            # 构建系统提示词 - 增加时间信息
            from datetime import datetime
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            system_prompt = f"你是一个智能对话分析助手，负责判断是否适合发送主动消息。当前时间: {current_time}。请根据提供的对话历史和上下文信息，判断现在是否适合发送主动消息。请在回复中包含 ^&YES&^ 表示应该发送主动消息，或 ^&NO&^ 表示不应该发送主动消息。"

            # 详细记录给LLM的整体信息
            self.logger.info(f"LLM决策请求 - 系统提示: {system_prompt}")
            self.logger.info(f"LLM决策请求 - 用户提示长度: {len(prompt)} 字符")
            if self.config.get("debug_show_full_prompt", True):
                self.logger.info(f"LLM决策请求 - 完整用户提示:\n{prompt}")
            else:
                self.logger.info("LLM决策请求 - 用户提示内容已省略（可通过配置开启详细显示）")

            # 调用LLM - 使用AstrBot核心系统的方式
            self.logger.info("正在调用LLM生成响应...")
            response = await provider.text_chat(
                prompt=prompt,
                system_prompt=system_prompt
            )

            if not response:
                self.logger.error("LLM响应为None")
                return False, "LLM响应为None"

            if not response.completion_text:
                self.logger.error("LLM响应的completion_text为空")
                return False, "LLM响应的completion_text为空"

            # 记录LLM的回复
            response_text = response.completion_text.strip()
            self.logger.info(f"LLM决策完整回复: {response_text}")

            if "^&YES&^" in response_text:
                self.logger.info("✅ LLM决策结果: 发送主动消息")
                return True, response_text
            elif "^&NO&^" in response_text:
                self.logger.info("❌ LLM决策结果: 不发送主动消息")
                return False, response_text
            else:
                self.logger.warning(f"⚠️ LLM返回了无法识别的响应: {response_text}")
                return False, response_text

        except Exception as e:
            self.logger.error(f"❌ 调用LLM进行决策时出现错误: {e}")
            return False, f"调用LLM时出现错误: {str(e)}"

    async def _call_llm_for_topic(self, prompt: str) -> Optional[str]:
        """调用LLM生成话题"""
        try:
            # 获取LLM提供者 - 使用AstrBot核心系统的方式
            provider = self.context.get_using_provider()
            if not provider:
                self.logger.info("没有可用的LLM提供者")
                return None

            # 构建系统提示词
            system_prompt = "你是一个智能话题生成助手，负责生成自然的对话话题。请根据提供的对话历史，生成一个适合当前对话氛围的话题。话题应该自然、有趣，并且能够引导对话继续。"
            
            # 记录给LLM的整体信息
            self.logger.info(f"LLM话题生成请求 - 系统提示: {system_prompt}")
            self.logger.info(f"LLM话题生成请求 - 用户提示长度: {len(prompt)} 字符")

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