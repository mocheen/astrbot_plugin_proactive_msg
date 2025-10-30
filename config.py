"""
配置管理模块
负责主动消息插件的配置管理
"""
import json
import os
from typing import Dict, Any, Optional


class ConfigManager:
    """配置管理器"""

    def __init__(self, config_path: str = "data/config/proactive_msg_config.json"):
        self.config_path = config_path
        self.config: Dict[str, Any] = self._load_default_config()
        self._load_config()

    def _load_default_config(self) -> Dict[str, Any]:
        """加载默认配置"""
        return {
            "poll_interval": "10min",
            "no_message_threshold": "30min",
            "reply_frequency": "moderate",
            "enable_time_check": True,
            "admin_only": False,
            "debug_trigger_on_init": True,  # 默认启用调试触发，方便调试
            "debug_show_full_prompt": True  # 显示完整的提示词内容用于调试
        }

    def _load_config(self):
        """从文件加载配置"""
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    saved_config = json.load(f)
                    self.config.update(saved_config)
        except Exception as e:
            print(f"加载配置文件失败: {e}")

    def _save_config(self):
        """保存配置到文件"""
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存配置文件失败: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置项"""
        return self.config.get(key, default)

    def set(self, key: str, value: Any):
        """设置配置项"""
        self.config[key] = value
        self._save_config()

    def get_all(self) -> Dict[str, Any]:
        """获取所有配置"""
        return self.config.copy()

    def reset_to_default(self):
        """重置为默认配置"""
        self.config = self._load_default_config()
        self._save_config()

    @property
    def poll_interval(self) -> str:
        """获取轮询间隔"""
        return self.get("poll_interval", "10min")

    @property
    def no_message_threshold(self) -> str:
        """获取无消息时间阈值"""
        return self.get("no_message_threshold", "30min")

    @property
    def reply_frequency(self) -> str:
        """获取回复频率模式"""
        return self.get("reply_frequency", "moderate")

    @property
    def enable_time_check(self) -> bool:
        """获取是否启用时间检查"""
        return self.get("enable_time_check", True)

    @property
    def admin_only(self) -> bool:
        """获取是否仅对管理员会话启用"""
        return self.get("admin_only", False)

    @property
    def debug_trigger_on_init(self) -> bool:
        """获取是否在初始化时触发调试轮询"""
        return self.get("debug_trigger_on_init", False)

    @property
    def debug_show_full_prompt(self) -> bool:
        """获取是否显示完整提示词用于调试"""
        return self.get("debug_show_full_prompt", True)


# 全局配置管理器实例
config_manager = ConfigManager()