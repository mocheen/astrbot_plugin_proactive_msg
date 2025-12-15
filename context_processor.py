"""
上下文处理器模块
复用AstrBot主机器人的上下文截断算法，确保插件获取与主机器人LLM请求时相同的历史消息
"""
import json
import logging
from typing import List, Dict, Any, Optional
from astrbot.api import logger


class ContextProcessor:
    """上下文处理器 - 复用主机器人的上下文截断算法"""
    
    def __init__(self, context):
        self.context = context
        self.logger = logger
        
        # 从主机器人配置中获取上下文长度参数
        self._load_context_config()
    
    def _load_context_config(self):
        """加载主机器人的上下文配置参数"""
        try:
            # 获取AstrBot配置
            config = self.context.get_config()
            
            # 获取provider_settings中的上下文相关配置
            provider_settings = config.get("provider_settings", {})
            
            # 读取max_context_length和dequeue_context_length
            self.max_context_length = provider_settings.get("max_context_length", -1)
            self.dequeue_context_length = provider_settings.get("dequeue_context_length", 1)
            
            self.logger.info(f"加载上下文配置: max_context_length={self.max_context_length}, "
                           f"dequeue_context_length={self.dequeue_context_length}")
            
        except Exception as e:
            self.logger.error(f"加载上下文配置失败: {e}, 使用默认值")
            self.max_context_length = -1
            self.dequeue_context_length = 1
    
    def apply_context_limit(self, contexts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        应用主机器人的上下文截断算法
        复用llm_request.py中的截断逻辑
        
        Args:
            contexts: 原始上下文列表
            
        Returns:
            截断后的上下文列表
        """
        if not contexts:
            return []
        
        # 如果max_context_length为-1，表示不限制上下文长度
        if self.max_context_length == -1:
            self.logger.debug("上下文长度无限制(max_context_length=-1)，返回原始上下文")
            return contexts
        
        # 计算上下文长度（每2条消息算一个完整的问答对）
        context_length = len(contexts) // 2
        
        # 如果上下文长度未超过限制，返回原始上下文
        if context_length <= self.max_context_length:
            self.logger.debug(f"上下文长度({context_length})未超过限制({self.max_context_length})，返回原始上下文")
            return contexts
        
        # 应用截断算法 - 复用主机器人的逻辑
        self.logger.info(f"上下文长度({context_length})超过限制({self.max_context_length})，开始截断")
        
        try:
            # 计算需要保留的上下文数量
            keep_count = (self.max_context_length - self.dequeue_context_length + 1) * 2
            
            # 从末尾开始截取指定数量的上下文
            truncated_contexts = contexts[-keep_count:]
            
            # 确保截断后的上下文格式正确（第一个消息必须是user角色）
            truncated_contexts = self._ensure_context_format(truncated_contexts)
            
            self.logger.info(f"上下文截断完成: 原始长度={len(contexts)}, 截断后长度={len(truncated_contexts)}")
            return truncated_contexts
            
        except Exception as e:
            self.logger.error(f"上下文截断失败: {e}, 返回原始上下文")
            return contexts
    
    def _ensure_context_format(self, contexts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        确保上下文格式正确（第一个消息必须是user角色）
        复用主机器人的格式检查逻辑
        """
        if not contexts:
            return contexts
        
        try:
            # 找到第一个role为user的索引
            user_index = None
            for i, msg in enumerate(contexts):
                if msg.get("role") == "user":
                    user_index = i
                    break
            
            # 如果找到了user角色消息，确保从该位置开始
            if user_index is not None and user_index > 0:
                self.logger.debug(f"找到第一个user角色消息在索引{user_index}，从该位置开始")
                return contexts[user_index:]
            
            # 如果没有找到user角色消息，返回原始上下文
            if user_index is None:
                self.logger.warning("未找到user角色消息，返回原始上下文")
                return contexts
            
            return contexts
            
        except Exception as e:
            self.logger.error(f"上下文格式检查失败: {e}, 返回原始上下文")
            return contexts
    
    def extract_contexts_with_timestamp(self, conversation_history: str) -> List[Dict[str, Any]]:
        """
        从会话历史中提取带时间戳的上下文
        
        Args:
            conversation_history: 会话历史的JSON字符串
            
        Returns:
            带时间戳的上下文列表
        """
        try:
            if not conversation_history:
                return []
            
            # 解析JSON格式的会话历史
            if isinstance(conversation_history, str):
                contexts = json.loads(conversation_history)
            else:
                contexts = conversation_history
            
            if not isinstance(contexts, list):
                self.logger.warning("会话历史格式不是列表，返回空列表")
                return []
            
            # 应用上下文长度限制
            processed_contexts = self.apply_context_limit(contexts)
            
            self.logger.info(f"提取带时间戳的上下文: 原始数量={len(contexts)}, 处理后数量={len(processed_contexts)}")
            return processed_contexts
            
        except json.JSONDecodeError as e:
            self.logger.error(f"解析会话历史JSON失败: {e}")
            return []
        except Exception as e:
            self.logger.error(f"提取上下文失败: {e}")
            return []
    
    def get_context_info(self) -> Dict[str, Any]:
        """获取当前上下文配置信息"""
        return {
            "max_context_length": self.max_context_length,
            "dequeue_context_length": self.dequeue_context_length,
            "context_limited": self.max_context_length != -1
        }