.DEFAULT_GOAL := help

PYTHON ?= python3

# 2925 业务常量：复制临时 profile、刷新扩展、批量自动运行时共用。
PRIMARY_2925_PROFILE ?= chrome-profile-29251
BASE_PROFILES_2925 ?= chrome-profile-29251 chrome-profile-29252
TEMP_PROFILE ?= chrome-profile-temp
TARGET_EXTENSION_ID ?= ckkgfnhgbfmfgpgdiiljgoggimflneii

# 自动运行公共参数：统一放在顶部，后续调整时只改这一段。
CLASH_AI_SWITCH_STRATEGY ?= reuse
CLASH_AI_SWITCH_REUSE_LIMIT ?= 5
PROXY_BLACKLIST_TTL_SECONDS ?= 86400
PROFILE_BLACKLIST_TTL_SECONDS ?= 43200
MAX_ATTEMPT_SECONDS ?= 1000
EMAILS_FILE ?= failed_add_phone_emails.txt
EMAILS_FILE_EXTRA_ROUNDS ?= 0

# 2925 批量运行参数。
BATCH_REPEAT_2925 ?= 20

# QQ 短信流程参数。
QQ_PROFILES ?= chrome-profile-qq1 chrome-profile-qq2
BATCH_REPEAT_QQ ?= 2
SMS_SOCKET_HOST ?= 0.0.0.0
SMS_SOCKET_PORT ?= 39393
SMS_CODE_INPUT_SELECTOR ?= .verify_code > input
SMS_CODE_SUBMIT_SELECTOR ?= .verify_code_bottom > button

.PHONY: help \
	prepare-2925-work-profile \
	refresh-2925-extension \
	clean-runtime-env \
	run-2925-batch \
	run-2925-email-file-batch \
	init-temp-profile \
	run-qq-sms-batch

# 打印当前仓库的常用业务命令，减少回忆长命令的成本。
help:
	@printf '%s\n' \
	'可用目标：' \
	'  make prepare-2925-work-profile  # 复制 2925 主 profile 到临时 profile，手动补环境' \
	'  make refresh-2925-extension     # 给 2925 基准 profile 刷新本地解压扩展' \
	'  make clean-runtime-env          # 清理临时 profile 和自动运行生成的 runtime 目录' \
	'  make run-2925-batch            # 跑 2925 批量自动流程' \
	'  make run-2925-email-file-batch # 按邮箱文件重跑 2925 自动流程' \
	'  make init-temp-profile         # 初始化一个全新的临时 profile' \
	'  make run-qq-sms-batch          # 跑 QQ 短信验证码批量流程' \
	'' \
	'常用变量：' \
	'  PRIMARY_2925_PROFILE=$(PRIMARY_2925_PROFILE)' \
	'  BASE_PROFILES_2925=$(BASE_PROFILES_2925)' \
	'  TEMP_PROFILE=$(TEMP_PROFILE)' \
	'  TARGET_EXTENSION_ID=$(TARGET_EXTENSION_ID)' \
	'  EMAILS_FILE=$(EMAILS_FILE)' \
	'  EMAILS_FILE_EXTRA_ROUNDS=$(EMAILS_FILE_EXTRA_ROUNDS)' \
	'  QQ_PROFILES=$(QQ_PROFILES)' \
	'  SMS_SOCKET_PORT=$(SMS_SOCKET_PORT)' \
	'' \
	'覆盖示例：' \
	'  make run-2925-batch BATCH_REPEAT_2925=10' \
	'  make run-2925-email-file-batch EMAILS_FILE=emails.txt' \
	'  make run-2925-email-file-batch EMAILS_FILE_EXTRA_ROUNDS=2' \
	'  make run-qq-sms-batch SMS_SOCKET_PORT=40000'

# 从 2925 主 profile 复制出临时 profile，方便手动补充环境或验证设置。
prepare-2925-work-profile:
	$(PYTHON) copy_chrome_profile.py \
		--profile $(PRIMARY_2925_PROFILE) \
		--output-profile $(TEMP_PROFILE)

# 刷新 2925 基准 profile 中的解压扩展，保证后续自动运行使用最新代码。
refresh-2925-extension:
	$(PYTHON) reload_unpacked_extension.py \
		--profile $(BASE_PROFILES_2925) \
		--extension-id $(TARGET_EXTENSION_ID)

# 清理临时 profile 和运行期复制目录，开始新一轮任务前先把现场收干净。
clean-runtime-env:
	rm -rf -- "$(TEMP_PROFILE)"
	rm -rf -- chrome-profile-run*

# 跑 2925 批量自动流程，带节点复用和黑名单时长控制。
run-2925-batch:
	$(PYTHON) launch_fresh_chrome.py \
		--run-extension \
		--repeat-count $(BATCH_REPEAT_2925) \
		--clash-ai-switch-strategy $(CLASH_AI_SWITCH_STRATEGY) \
		--clash-ai-switch-reuse-limit $(CLASH_AI_SWITCH_REUSE_LIMIT) \
		--extension-id $(TARGET_EXTENSION_ID) \
		--profile $(BASE_PROFILES_2925) \
		--proxy-blacklist-ttl-seconds $(PROXY_BLACKLIST_TTL_SECONDS) \
		--profile-blacklist-ttl-seconds $(PROFILE_BLACKLIST_TTL_SECONDS) \
		--max-attempt-seconds $(MAX_ATTEMPT_SECONDS)

# 按邮箱文件逐条重跑 2925 自动流程，每个邮箱对应一轮。
run-2925-email-file-batch:
	$(PYTHON) launch_fresh_chrome.py \
		--run-extension \
		--emails-file $(EMAILS_FILE) \
		--emails-file-extra-rounds $(EMAILS_FILE_EXTRA_ROUNDS) \
		--clash-ai-switch-strategy $(CLASH_AI_SWITCH_STRATEGY) \
		--clash-ai-switch-reuse-limit $(CLASH_AI_SWITCH_REUSE_LIMIT) \
		--extension-id $(TARGET_EXTENSION_ID) \
		--profile $(BASE_PROFILES_2925) \
		--proxy-blacklist-ttl-seconds $(PROXY_BLACKLIST_TTL_SECONDS) \
		--profile-blacklist-ttl-seconds $(PROFILE_BLACKLIST_TTL_SECONDS) \
		--max-attempt-seconds $(MAX_ATTEMPT_SECONDS)

# 初始化一个全新的临时 profile，适合重新手动配置账号或浏览器环境。
init-temp-profile:
	$(PYTHON) init_chrome_profile.py \
		--profile $(TEMP_PROFILE)

# 跑 QQ 短信验证码批量流程，保持窗口可见并接收本地短信 socket 验证码。
run-qq-sms-batch:
	$(PYTHON) launch_fresh_chrome.py \
		--run-extension \
		--repeat-count $(BATCH_REPEAT_QQ) \
		--clash-ai-switch-strategy $(CLASH_AI_SWITCH_STRATEGY) \
		--clash-ai-switch-reuse-limit $(CLASH_AI_SWITCH_REUSE_LIMIT) \
		--extension-id $(TARGET_EXTENSION_ID) \
		--profile $(QQ_PROFILES) \
		--proxy-blacklist-ttl-seconds $(PROXY_BLACKLIST_TTL_SECONDS) \
		--profile-blacklist-ttl-seconds $(PROFILE_BLACKLIST_TTL_SECONDS) \
		--max-attempt-seconds $(MAX_ATTEMPT_SECONDS) \
		--no-auto-minimize \
		--sms-socket-host $(SMS_SOCKET_HOST) \
		--sms-socket-port $(SMS_SOCKET_PORT) \
		--sms-code-input-selector '$(SMS_CODE_INPUT_SELECTOR)' \
		--sms-code-submit-selector '$(SMS_CODE_SUBMIT_SELECTOR)'
