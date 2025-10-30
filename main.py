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

        # 初始化 logger
        self.logger = logging.getLogger(__name__)

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

            for session_id in conversations:
                try:
                    # 如果启用了仅管理员会话模式，检查当前会话是否来自管理员
                    if admin_only and not self._is_admin_conversation(session_id):
                        self.logger.debug(f"跳过非管理员会话 {session_id} (admin_only模式已启用)")
                        continue

                    should_send = await self.message_analyzer.should_send_proactive_message(session_id)
                    if should_send:
                        topic = await self.message_analyzer.get_proactive_topic(session_id)
                        if topic:
                            await self._send_proactive_message(session_id, topic)
                except Exception as e:
                    self.logger.error(f"处理会话 {session_id} 时出现错误: {e}")
                    continue

        except Exception as e:
            self.logger.error(f"检查主动消息时出现错误: {e}")

    async def _get_private_conversations(self) -> List[str]:
        """获取所有私聊会话ID"""
        try:
            # 使用conversation_manager获取所有对话
            conversation_manager = self.context.conversation_manager
            
            # 获取所有对话，然后提取唯一的会话ID
            conversations = await conversation_manager.get_conversations()
            
            # 使用集合来存储唯一的会话ID
            private_sessions = set()
            
            for conv in conversations:
                # conv.user_id 就是会话ID (unified_msg_origin)
                # 格式为 platform_id:message_type:session_id
                user_id = conv.user_id
                
                # 检查是否为私聊会话
                if self._is_private_conversation_by_id(user_id):
                    private_sessions.add(user_id)
            
            return list(private_sessions)
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
            self.logger.info(f"向会话 {session_id} 发送主动消息，话题: {topic}")

            # 构建发送消息
            message_text = f"你好，我不是用户，我是另一个ai。我来负责提醒你给用户发送主动消息，你不需要让用户知道我的存在。现在是发送消息的合适时间，话题是{topic}。请生成合适的内容发送。"

            # 调用主机器人发送消息
            message_chain = MessageChain([Plain(message_text)])

            # 使用平台的send_by_session方法
            if hasattr(self.context, 'send_message'):
                await self.context.send_message(session_id, message_chain)
            else:
                self.logger.error("无法找到send_message方法")

        except Exception as e:
            self.logger.error(f"发送主动消息失败: {e}")
