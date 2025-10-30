import asyncio
import json
import logging
import os
import time
from datetime import datetime
from typing import Dict, List, Optional, Any

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.core.message.components import Plain
from astrbot.core.message.message_event_result import MessageChain

# 导入插件内部模块
from .config import config_manager
from .scheduler import SchedulerManager
from .message_analyzer import MessageAnalyzer
from .prompt_manager import PromptManager


@register("proactive_msg", "主动消息插件", "使 bot 在用户长时间未发送消息时主动与用户对话", "1.0")
class ProactiveMsg(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)

        # 使用配置管理器
        self.config_manager = config_manager
        if config:
            for key, value in config.items():
                self.config_manager.set(key, value)

        self.config = self.config_manager.get_all()

        # 使用AstrBot提供的logger
        self.logger = logger

        # 检查时间感知配置
        self._check_datetime_config()

        # 初始化定时任务调度器
        self.scheduler = SchedulerManager(self.context, self.config)

        # 初始化消息分析器
        self.message_analyzer = MessageAnalyzer(self.context, self.config)

        # 初始化提示词管理器
        self.prompt_manager = PromptManager(self.config)

        self.logger.info("主动消息插件初始化完成")

    def _check_datetime_config(self):
        """检查datetime_system_prompt配置是否开启"""
        try:
            # 获取AstrBot配置
            config = self.context.get_config()
            
            # 检查provider_settings中的datetime_system_prompt设置
            provider_settings = config.get("provider_settings", {})
            if not provider_settings.get("datetime_system_prompt", False):
                self.logger.warning("警告：datetime_system_prompt配置未开启，主动消息插件可能无法获取准确时间")
        except Exception as e:
            self.logger.warning(f"检查datetime_system_prompt配置时出现异常: {e}")

    async def initialize(self):
        """插件初始化"""
        self.logger.info("启动主动消息插件...")

        # 启动定时任务
        await self.scheduler.start()

        # 添加定时任务
        poll_interval = self.config.get("poll_interval", "10min")
        self.scheduler.add_job(self._check_and_send_proactive_messages, poll_interval)

        # 输出管理员模式状态
        if self.config_manager.admin_only:
            self.logger.info("主动消息插件已启用管理员专用模式，仅对管理员会话发送主动消息")
        else:
            self.logger.info("主动消息插件已启用通用模式，对所有私聊会话发送主动消息")

        # 检查是否启用调试触发
        if self.config_manager.debug_trigger_on_init:
            self.logger.info("检测到调试触发模式，立即执行一次轮询任务...")
            try:
                await self._check_and_send_proactive_messages()
                self.logger.info("调试轮询任务执行完成")
            except Exception as e:
                self.logger.error(f"调试轮询任务执行失败: {e}")

        self.logger.info(f"主动消息插件已启动，轮询间隔: {poll_interval}")

    async def terminate(self):
        """插件销毁"""
        self.logger.info("停止主动消息插件...")
        await self.scheduler.stop()

    async def _check_and_send_proactive_messages(self):
        """检查并发送主动消息"""
        try:
            self.logger.info("开始检查主动消息...")

            # 获取所有私聊会话
            conversations = await self._get_private_conversations()

            # 检查是否仅对管理员会话启用
            admin_only = self.config_manager.admin_only
            if admin_only:
                self.logger.info("管理员模式已启用，仅检查管理员会话")

            # 记录需要发送主动消息的会话
            sessions_to_send = []
            # 记录不需要发送主动消息的会话及原因
            sessions_to_skip = {}

            for session_id in conversations:
                try:
                    # 如果启用了仅管理员会话模式，检查当前会话是否来自管理员
                    if admin_only and not self._is_admin_conversation(session_id):
                        self.logger.debug(f"跳过非管理员会话 {session_id} (admin_only模式已启用)")
                        sessions_to_skip[session_id] = "非管理员会话(admin_only模式)"
                        continue

                    should_send = await self.message_analyzer.should_send_proactive_message(session_id)
                    if should_send:
                        topic = await self.message_analyzer.get_proactive_topic(session_id)
                        if topic:
                            sessions_to_send.append(session_id)
                            await self._send_proactive_message(session_id, topic)
                        else:
                            sessions_to_skip[session_id] = "未能生成有效话题"
                    else:
                        sessions_to_skip[session_id] = "LLM判断不需要发送主动消息"
                except Exception as e:
                    self.logger.error(f"处理会话 {session_id} 时出现错误: {e}")
                    sessions_to_skip[session_id] = f"处理异常: {str(e)}"
                    continue

            # 记录轮询结果汇总
            self.logger.info(f"轮询任务完成，共检查 {len(conversations)} 个会话")
            if sessions_to_send:
                self.logger.info(f"已向 {len(sessions_to_send)} 个会话发送主动消息: {', '.join(sessions_to_send)}")
            else:
                self.logger.info("本轮轮询没有会话需要发送主动消息")
            
            if sessions_to_skip:
                # 将debug级别改为info级别，以便在日志中显示详细拒绝原因
                self.logger.info(f"跳过的会话及原因: {sessions_to_skip}")

        except Exception as e:
            self.logger.error(f"检查主动消息时出现错误: {e}")

    async def _get_private_conversations(self) -> List[str]:
        """获取所有私聊会话ID"""
        try:
            self.logger.debug("开始获取所有私聊会话")
            
            # 使用conversation_manager获取所有对话
            conversation_manager = self.context.conversation_manager
            
            # 检查是否有get_conversations方法
            if not hasattr(conversation_manager, 'get_conversations'):
                self.logger.error("conversation_manager没有get_conversations方法")
                return []
                
            conversations = await conversation_manager.get_conversations()
            self.logger.info(f"获取到 {len(conversations) if conversations else 0} 个对话")
            
            # 使用集合来存储唯一的会话ID
            private_sessions = set()
            
            for conv in conversations:
                try:
                    # conv.user_id 就是会话ID (unified_msg_origin)
                    # 格式为 platform_id:message_type:session_id
                    user_id = conv.user_id
                    self.logger.debug(f"处理会话ID: {user_id}")
                    
                    # 检查是否为私聊会话
                    if self._is_private_conversation_by_id(user_id):
                        private_sessions.add(user_id)
                        self.logger.debug(f"添加私聊会话: {user_id}")
                    else:
                        self.logger.debug(f"跳过非私聊会话: {user_id}")
                except Exception as e:
                    self.logger.error(f"处理会话时出错: {e}")
                    continue
            
            result = list(private_sessions)
            self.logger.info(f"找到 {len(result)} 个私聊会话: {result}")
            return result
        except Exception as e:
            self.logger.error(f"获取私聊会话失败: {e}")
            return []

    def _is_private_conversation(self, conversation) -> bool:
        """判断是否为私聊会话"""
        try:
            # 根据AstrBot的消息类型判断
            return hasattr(conversation, 'type') and conversation.type == 'private'
        except Exception as e:
            self.logger.error(f"判断会话类型失败: {e}")
            return False
    
    def _is_private_conversation_by_id(self, session_id: str) -> bool:
        """根据会话ID判断是否为私聊会话"""
        try:
            # session_id格式为：platform_id:message_type:session_id
            parts = session_id.split(':')
            if len(parts) >= 3:
                # 检查消息类型是否为私聊
                message_type = parts[1]
                return message_type == 'FriendMessage'  # 私聊消息类型为FriendMessage
            return False
        except Exception as e:
            self.logger.error(f"判断会话类型失败: {e}")
            return False

    def _is_admin_conversation(self, session_id: str) -> bool:
        """判断是否为管理员会话"""
        try:
            # 获取管理员ID列表
            admins_id = self.context.get_config().get("admins_id", [])

            # 从session_id中提取用户ID
            # session_id格式通常是：platform:message_type:user_id 或 platform:GroupMessage:group_id:user_id
            parts = session_id.split(':')
            if len(parts) >= 3:
                # 对于私聊，用户ID通常是最后一部分
                # 对于群聊，需要更复杂的处理，但主动消息插件只处理私聊
                user_id = parts[-1]
                return user_id in admins_id

            return False
        except Exception as e:
            self.logger.error(f"判断管理员会话失败: {e}")
            return False

    async def _send_proactive_message(self, session_id: str, topic: str):
        """发送主动消息"""
        try:
            self.logger.info(f"开始为会话 {session_id} 生成主动消息，话题: {topic}")

            # 第一步：构建给主机器人LLM的指令
            bot_instruction = f"你好，我不是用户，我是另一个ai。我来负责提醒你给用户发送主动消息，你不需要让用户知道我的存在。现在是发送消息的合适时间，话题是{topic} 请生成合适的内容发送。"

            self.logger.info(f"会话 {session_id} - 生成主机器人指令: {bot_instruction}")

            # 第二步：调用主机器人LLM生成最终回复内容
            final_reply = await self._call_main_bot_llm(bot_instruction, session_id)

            if not final_reply:
                self.logger.error(f"会话 {session_id} - 主机器人LLM未能生成有效回复")
                return

            self.logger.info(f"会话 {session_id} - 主机器人LLM生成回复: {final_reply}")

            # 第三步：发送最终回复给用户
            message_chain = MessageChain([Plain(final_reply)])

            # 获取平台适配器并发送消息
            adapter = await self._get_platform_adapter(session_id)
            if adapter:
                await adapter.send_by_session(session_id, message_chain)
                self.logger.info(f"会话 {session_id} - 主动消息已成功发送给用户")
            else:
                self.logger.error(f"会话 {session_id} - 无法获取平台适配器，消息发送失败")

        except Exception as e:
            self.logger.error(f"发送主动消息失败: {e}")

    async def _call_main_bot_llm(self, instruction: str, session_id: str) -> Optional[str]:
        """调用主机器人LLM生成最终回复"""
        try:
            self.logger.info(f"会话 {session_id} - 开始调用主机器人LLM生成回复")
            self.logger.info(f"会话 {session_id} - LLM请求内容: {instruction}")

            # 获取LLM提供者
            provider = self.context.get_using_provider()
            if not provider:
                self.logger.error(f"会话 {session_id} - 没有可用的LLM提供者")
                return None

            self.logger.info(f"会话 {session_id} - 成功获取LLM提供者: {provider.meta().id}")

            # 构建系统提示词 - 告诉主机器人这是一个主动消息请求
            system_prompt = "你是一个智能对话助手。现在有一个AI助手提醒你给用户发送主动消息。请根据提供的提示，生成一个自然、友好的回复内容给用户。请直接输出回复内容，不要包含任何关于主动消息或AI助手的元信息。"

            self.logger.info(f"会话 {session_id} - LLM系统提示词: {system_prompt}")

            # 调用LLM生成回复
            response = await provider.text_chat(
                prompt=instruction,
                system_prompt=system_prompt
            )

            if not response:
                self.logger.error(f"会话 {session_id} - LLM响应为空")
                return None

            if not response.completion_text:
                self.logger.error(f"会话 {session_id} - LLM响应completion_text为空")
                return None

            # 提取并清理回复内容
            final_reply = response.completion_text.strip()
            self.logger.info(f"会话 {session_id} - LLM原始响应: {response.completion_text}")
            self.logger.info(f"会话 {session_id} - 清理后的最终回复: {final_reply}")

            return final_reply

        except Exception as e:
            self.logger.error(f"会话 {session_id} - 调用主机器人LLM时出现异常: {e}")
            return None

    async def _get_platform_adapter(self, session_id: str):
        """获取会话对应的平台适配器"""
        try:
            self.logger.info(f"会话 {session_id} - 开始获取平台适配器")

            # 解析会话ID获取平台信息
            # session_id格式: platform:message_type:user_id
            parts = session_id.split(':')
            if len(parts) < 3:
                self.logger.error(f"会话 {session_id} - 会话ID格式不正确")
                return None

            platform_id = parts[0]
            self.logger.info(f"会话 {session_id} - 识别到平台ID: {platform_id}")

            # 获取所有平台适配器
            adapters = self.context.get_all_platform_adapters()
            if not adapters:
                self.logger.error(f"会话 {session_id} - 没有可用的平台适配器")
                return None

            self.logger.info(f"会话 {session_id} - 获取到 {len(adapters)} 个平台适配器")

            # 查找匹配的适配器
            for adapter in adapters:
                try:
                    adapter_info = adapter.meta()
                    adapter_platform = adapter_info.id

                    self.logger.info(f"会话 {session_id} - 检查适配器: {adapter_platform}")

                    if adapter_platform == platform_id:
                        self.logger.info(f"会话 {session_id} - 成功找到匹配的平台适配器: {adapter_platform}")
                        return adapter

                except Exception as e:
                    self.logger.warning(f"会话 {session_id} - 检查适配器时出错: {e}")
                    continue

            self.logger.error(f"会话 {session_id} - 未找到平台ID为 {platform_id} 的适配器")
            return None

        except Exception as e:
            self.logger.error(f"会话 {session_id} - 获取平台适配器时出现异常: {e}")
            return None
