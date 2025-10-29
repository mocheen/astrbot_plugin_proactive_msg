"""
提示词管理器模块
负责主动消息插件的提示词管理，支持不同频率模式的提示词
"""
import os
import json
from typing import Dict, Optional


class PromptManager:
    """提示词管理器"""

    def __init__(self, config: dict):
        self.config = config

        # 默认提示词模板路径
        self.template_path = os.path.join(os.path.dirname(__file__), 'prompts')

        # 预设模式描述
        self.frequency_modes = {
            "rare": {
                "name": "稀少模式",
                "description": "减少主动消息频率，适用于不希望打扰用户的场景",
                "base_frequency": "平均1小时回复"
            },
            "moderate": {
                "name": "适中模式",
                "description": "平衡的主动消息频率，适用于一般场景",
                "base_frequency": "平均30分钟回复"
            },
            "frequent": {
                "name": "频繁模式",
                "description": "增加主动消息频率，适用于需要高互动的场景",
                "base_frequency": "平均10分钟回复"
            }
        }

        # 初始化提示词模板
        self._init_prompt_templates()

    def _init_prompt_templates(self):
        """初始化提示词模板"""
        # 确保模板目录存在
        os.makedirs(self.template_path, exist_ok=True)

        # 创建模板文件
        self._create_analysis_prompt_template()
        self._create_topic_prompt_template()

    def _create_analysis_prompt_template(self):
        """创建分析提示词模板"""
        template_file = os.path.join(self.template_path, 'analysis_prompt_template.txt')

        if not os.path.exists(template_file):
            template_content = """你是一个智能对话分析助手。请根据以下对话历史和时间信息，判断现在是否适合发送主动消息给用户。

对话历史:
{DIALOGUE_HISTORY}

当前时间信息: {TIME_INFO}
回复频率要求: {FREQUENCY_INFO}

请进行智能分析：
1. 考虑对话的自然程度和当前时间是否合适
2. 考虑用户可能正在忙或有其他事情
3. 避免在可能打扰用户的时候发送消息
4. 确保发送的消息有实际意义和价值

判断规则（请严格遵守回复格式，方便程序识别和截取）：
- 如果适合发送主动消息，请回复: "^&YES&^"
- 如果不适合发送主动消息，请回复: "^&NO^"

请做出最合适的判断。"""

            with open(template_file, 'w', encoding='utf-8') as f:
                f.write(template_content)

    def _create_topic_prompt_template(self):
        """创建话题生成提示词模板"""
        template_file = os.path.join(self.template_path, 'topic_prompt_template.txt')

        if not os.path.exists(template_file):
            template_content = """你是一个智能话题生成助手。基于以下对话历史，生成一个自然的主动话题。

对话历史:
{DIALOGUE_HISTORY}

要求：
1. 话题要与当前对话相关或自然延伸
2. 话题应该有趣、有意义，能够引导用户继续对话
3. 避免敏感或不适当的话题
4. 话题应该简洁明了，长度在20-50字左右

请直接返回话题内容，不要包含其他说明。"""

            with open(template_file, 'w', encoding='utf-8') as f:
                f.write(template_content)

    def get_analysis_prompt(self, dialogue_history: str, time_info: str = "", frequency_info: str = "") -> str:
        """获取分析提示词"""
        try:
            # 如果没有提供频率信息，则从配置获取
            if not frequency_info:
                frequency_mode = self.config.get("reply_frequency", "moderate")
                frequency_info = self._get_frequency_description(frequency_mode)

            # 构建提示词变量
            variables = {
                "DIALOGUE_HISTORY": dialogue_history,
                "TIME_INFO": time_info,
                "FREQUENCY_INFO": frequency_info
            }

            # 从模板文件读取
            template_file = os.path.join(self.template_path, 'analysis_prompt_template.txt')
            with open(template_file, 'r', encoding='utf-8') as f:
                template = f.read()

            # 替换变量
            prompt = template.format(**variables)
            return prompt

        except Exception as e:
            # 如果模板文件读取失败，返回默认提示词
            return self._get_default_analysis_prompt(dialogue_history, time_info, frequency_info)

    def get_topic_prompt(self, dialogue_history: str) -> str:
        """获取话题生成提示词"""
        try:
            # 构建提示词变量
            variables = {
                "DIALOGUE_HISTORY": dialogue_history
            }

            # 从模板文件读取
            template_file = os.path.join(self.template_path, 'topic_prompt_template.txt')
            with open(template_file, 'r', encoding='utf-8') as f:
                template = f.read()

            # 替换变量
            prompt = template.format(**variables)
            return prompt

        except Exception as e:
            # 如果模板文件读取失败，返回默认提示词
            return self._get_default_topic_prompt(dialogue_history)

    def _get_frequency_description(self, mode: str) -> str:
        """获取频率模式描述"""
        mode_info = self.frequency_modes.get(mode, self.frequency_modes["moderate"])
        return f"{mode_info['name']}: {mode_info['base_frequency']}，偶尔可以例外"

    def _get_default_analysis_prompt(self, dialogue_history: str, time_info: str, frequency_info: str) -> str:
        """获取默认分析提示词"""
        if not frequency_info:
            frequency_mode = self.config.get("reply_frequency", "moderate")
            frequency_info = self._get_frequency_description(frequency_mode)

        return f"""你是一个智能对话分析助手。请根据以下对话历史和时间信息，判断现在是否适合发送主动消息给用户。

对话历史:
{dialogue_history}

当前时间信息: {time_info}
回复频率要求: {frequency_info}

请进行智能分析：
1. 考虑对话的自然程度和当前时间是否合适
2. 考虑用户可能正在忙或有其他事情
3. 避免在可能打扰用户的时候发送消息
4. 确保发送的消息有实际意义和价值

判断规则（请严格遵守回复格式，方便程序识别和截取）：
- 如果适合发送主动消息，请回复: "^&YES&^"
- 如果不适合发送主动消息，请回复: "^&NO^"

请做出最合适的判断。"""

    def _get_default_topic_prompt(self, dialogue_history: str) -> str:
        """获取默认话题生成提示词"""
        return f"""你是一个智能话题生成助手。基于以下对话历史，生成一个自然的主动话题。

对话历史:
{dialogue_history}

要求：
1. 话题要与当前对话相关或自然延伸
2. 话题应该有趣、有意义，能够引导用户继续对话
3. 避免敏感或不适当的话题
4. 话题应该简洁明了，长度在20-50字左右

请直接返回话题内容，不要包含其他说明。"""

    def get_frequency_mode_info(self, mode: str) -> Dict:
        """获取频率模式信息"""
        return self.frequency_modes.get(mode, self.frequency_modes["moderate"])

    def get_all_frequency_modes(self) -> Dict[str, Dict]:
        """获取所有频率模式"""
        return self.frequency_modes.copy()

    def update_frequency_mode(self, mode: str, description: str, base_frequency: str):
        """更新频率模式"""
        if mode in self.frequency_modes:
            self.frequency_modes[mode].update({
                "description": description,
                "base_frequency": base_frequency
            })

    def is_valid_frequency_mode(self, mode: str) -> bool:
        """检查频率模式是否有效"""
        return mode in self.frequency_modes

    def get_available_modes(self) -> list:
        """获取可用的频率模式列表"""
        return list(self.frequency_modes.keys())