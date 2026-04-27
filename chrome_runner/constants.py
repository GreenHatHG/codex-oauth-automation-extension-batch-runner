"""Shared constants for Chrome launch and extension automation."""

from pathlib import Path

CHROME_EXECUTABLE = Path(
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
)
BASE_PROFILE_DIR_NAME = "chrome-profile"
RUNTIME_PROFILE_PREFIX = "chrome-profile-run"
START_PAGE = "about:blank"

DEVTOOLS_HOST = "127.0.0.1"
DEVTOOLS_READY_TIMEOUT_SECONDS = 15.0
DEVTOOLS_POLL_INTERVAL_SECONDS = 0.2
DEVTOOLS_HTTP_TIMEOUT_SECONDS = 2.0
START_PAGE_REUSE_TIMEOUT_SECONDS = 2.0
PAGE_READY_TIMEOUT_SECONDS = 15.0
BUTTON_CLICK_TIMEOUT_SECONDS = 15.0
RUN_MONITOR_POLL_INTERVAL_SECONDS = 2.0
RUN_MONITOR_STAGNATION_TIMEOUT_SECONDS = 300.0

CLASH_REQUEST_TIMEOUT_SECONDS = 5.0
CLASH_REQUEST_RETRY_ATTEMPTS = 3
CLASH_REQUEST_RETRY_DELAY_SECONDS = 1.0
CLASH_BASE_URL = "http://127.0.0.1:9090"
CLASH_GROUP_NAME = "Openai节点"
CLASH_DELAY_TEST_URL = "https://chatgpt.com/"
CLASH_DELAY_TIMEOUT_MS = 5000
CLASH_SKIP_NAME_WORDS = (
    "流量",
    "套餐到期",
    "建议：",
    "距离下次重置",
)
CLASH_SKIP_PROXY_TYPES = frozenset(
    {
        "Selector",
        "Fallback",
        "URLTest",
        "LoadBalance",
        "Direct",
        "Reject",
    }
)
CLASH_AI_SWITCH_ERROR_PREFIX = "自动运行前置动作执行失败："
DEFAULT_LOCAL_BLACKLIST_TTL_SECONDS = 12 * 60 * 60
PROXY_BLACKLIST_FILE_NAME = ".proxy-blacklist.json"
PROXY_BLACKLIST_COOLDOWN_KIND_SUCCESS = "success"
PROXY_BLACKLIST_COOLDOWN_KIND_UNSUCCESSFUL = "unsuccessful"
DEFAULT_PROXY_BLACKLIST_SUCCESS_TTL_SECONDS = 2 * 60 * 60
DEFAULT_PROXY_BLACKLIST_UNSUCCESSFUL_TTL_SECONDS = DEFAULT_LOCAL_BLACKLIST_TTL_SECONDS
BATCH_PROXY_FAILURE_BLACKLIST_THRESHOLD = 2
PROXY_SUCCESS_FAILURE_THRESHOLD = 3
PROXY_STATS_FILE_NAME = ".proxy-stats.json"
PROFILE_BLACKLIST_FILE_NAME = ".profile-blacklist.json"
DEFAULT_PROFILE_BLACKLIST_TTL_SECONDS = DEFAULT_LOCAL_BLACKLIST_TTL_SECONDS
PROFILE_BLACKLIST_SIGNAL_TEXTS = (
    "子账号数量已达上限",
    "QQ 别名开通失败：操作过于频繁，请稍后重试。",
    "QQ 别名开通失败",
)
PROFILE_MAILBOX_SITE_REFERENCES = (
    "2925.com",
    "wx.mail.qq.com",
)
PROFILE_PREFERENCES_RELATIVE_PATH = ("Default", "Preferences")
FAILED_ADD_PHONE_EMAILS_FILE_NAME = "failed_add_phone_emails.txt"
FAILED_ADD_PHONE_EMAIL_RETRY_COUNTS_FILE_NAME = (
    "failed_add_phone_email_retry_counts.json"
)
FAILED_SIGNUP_EMAILS_FILE_NAME = "failed_signup_emails.txt"
FAILED_SIGNUP_EMAIL_RETRY_COUNTS_FILE_NAME = (
    "failed_signup_email_retry_counts.json"
)
DEFAULT_FAILED_ADD_PHONE_EMAIL_MAX_RETRIES = 3
CURRENT_EMAIL_LOG_PREFIX = "当前邮箱："

CHROME_FLAGS = (
    "--no-first-run",
    "--no-default-browser-check",
)
CHROME_NO_STARTUP_WINDOW_FLAG = "--no-startup-window"
DEVTOOLS_TARGET_DISCOVERY_TIMEOUT_SECONDS = 15.0
STALE_LOCK_FILE_NAMES = (
    "SingletonCookie",
    "SingletonLock",
    "SingletonSocket",
)
CHROME_SHUTDOWN_TIMEOUT_SECONDS = 10.0
PROFILE_DELETE_TIMEOUT_SECONDS = 10.0
PROCESS_TERMINATION_POLL_SECONDS = 0.2
DEFAULT_SMS_SOCKET_HOST = "127.0.0.1"
DEFAULT_SMS_CODE_TIMEOUT_SECONDS = 120
DEFAULT_SMS_CODE_REGEX = r"(?<!\d)(\d{4,8})(?!\d)"
SMS_RECEIVER_LISTEN_BACKLOG = 5
SMS_RECEIVER_BUFFER_SIZE = 4096
SMS_RECEIVER_ACCEPT_TIMEOUT_SECONDS = 0.5
SMS_RECEIVER_CONNECTION_TIMEOUT_SECONDS = 0.5
SMS_CODE_SUBMIT_DISCOVERY_TIMEOUT_SECONDS = 5.0
SMS_VERIFICATION_LOG_SIGNAL_TEXTS = (
    "短信验证码已请求成功，可以开始等待接收短信。",
    "请等待接收短信，收到后在当前页面输入验证码并点击提交验证，脚本会自动继续。",
)
DEFAULT_SMS_CODE_INPUT_SELECTORS = (
    "input[autocomplete='one-time-code']",
    "input[inputmode='numeric']",
    "input[name*='code' i]",
    "input[id*='code' i]",
    "input[name*='otp' i]",
    "input[id*='otp' i]",
    "input[name*='verification' i]",
    "input[id*='verification' i]",
    "input[placeholder*='验证码']",
    "input[aria-label*='验证码']",
)
DEFAULT_SMS_CODE_SUBMIT_TEXTS = (
    "提交",
    "验证",
    "继续",
    "下一步",
    "confirm",
    "continue",
    "verify",
    "submit",
    "next",
)

TARGET_EXTENSION_ID = "niignaaoplafnpbcdgcgcajfjddcncgb"
EXTENSION_START_MODE_AUTO_RUN = "auto-run"
EXTENSION_START_MODE_REGISTERED_OAUTH_RETRY = "registered-oauth-retry"
EXTENSION_START_MODE_CHOICES = (
    EXTENSION_START_MODE_AUTO_RUN,
    EXTENSION_START_MODE_REGISTERED_OAUTH_RETRY,
)
AUTO_RUN_BUTTON_SELECTOR = "#btn-auto-run"
AUTO_RUN_NOW_BUTTON_SELECTOR = "#btn-auto-run-now"
AUTO_START_MODAL_SELECTOR = "#auto-start-modal"
AUTO_START_RESTART_BUTTON_SELECTOR = "#btn-auto-start-restart"
REGISTERED_OAUTH_RETRY_BUTTON_SELECTOR = "#btn-registered-oauth-retry"
EMAIL_INPUT_SELECTOR = "#input-email"
PASSWORD_INPUT_SELECTOR = "#input-password"
STATUS_BAR_SELECTOR = "#status-bar"
STATUS_DISPLAY_SELECTOR = "#display-status"
LOG_LINE_SELECTOR = "#log-area .log-line"
STEP_STATUS_SELECTOR = ".step-status"
EXTENSION_RESULT_LOG_LINE_LIMIT = 20

RUNNING_STATUS_TEXTS = (
    "运行中",
    "等待中",
    "重试中",
)
SCHEDULED_STATUS_TEXTS = (
    "计划中",
    "已计划",
)
SUCCESS_STATUS_TEXTS = (
    "全部步骤已完成",
    "全部步骤已跳过/完成",
)
FAILURE_STATUS_TEXTS = (
    "失败",
    "已停止",
)
ADD_PHONE_ERROR_SIGNAL_TEXTS = (
    "auth.openai.com/add-phone",
    "进入 add-phone",
    "手机号页面",
    "手机号页",
)

EXTENSION_START_SCRIPT_TEMPLATE = """
(() => {
  const autoRunButton = document.querySelector(%(auto_run_button)s);
  if (!autoRunButton) {
    return 'missing-auto-run-button';
  }

  const modal = document.querySelector(%(auto_start_modal)s);
  const restartButton = document.querySelector(%(restart_button)s);
  if (modal && !modal.hidden && restartButton && !restartButton.disabled) {
    restartButton.click();
    return 'clicked-restart';
  }

  const runNowButton = document.querySelector(%(run_now_button)s);
  if (runNowButton && !runNowButton.disabled) {
    const scheduleBar = runNowButton.closest('#auto-schedule-bar');
    const style = scheduleBar ? window.getComputedStyle(scheduleBar) : null;
    const visible = scheduleBar && !scheduleBar.hidden && style && style.display !== 'none';
    if (visible) {
      runNowButton.click();
      return 'clicked-run-now';
    }
  }

  const buttonText = (autoRunButton.textContent || '').trim();
  const startedLabels = %(running_labels)s;
  const scheduledLabels = %(scheduled_labels)s;
  if (autoRunButton.disabled || startedLabels.some((label) => buttonText.includes(label))) {
    return 'started';
  }
  if (scheduledLabels.some((label) => buttonText.includes(label))) {
    return 'scheduled';
  }

  autoRunButton.click();
  return 'clicked-auto-run';
})()
""".strip()

EXTENSION_START_REGISTERED_OAUTH_RETRY_SCRIPT_TEMPLATE = """
(() => {
  const retryButton = document.querySelector(%(retry_button_selector)s);
  if (!retryButton) {
    return 'missing-registered-oauth-retry-button';
  }

  const emailInput = document.querySelector(%(email_input_selector)s);
  if (!emailInput) {
    return 'missing-email-input';
  }

  const passwordInput = document.querySelector(%(password_input_selector)s);
  if (!passwordInput) {
    return 'missing-password-input';
  }

  const email = (emailInput.value || '').trim();
  if (!email) {
    return 'missing-email';
  }

  const password = (passwordInput.value || '').trim();
  if (!password) {
    return 'missing-password';
  }

  try {
    chrome.runtime.sendMessage({
      type: 'START_REGISTERED_OAUTH_RETRY',
      source: 'sidepanel',
      payload: {
        email,
        password,
      },
    }).catch((error) => {
      console.error('start-registered-oauth-retry-error', error);
    });
    return 'started';
  } catch (error) {
    return `start-registered-oauth-retry-error:${error?.message || String(error)}`;
  }
})()
""".strip()

EXTENSION_SAVE_EMAIL_SCRIPT_TEMPLATE = """
(async () => {
  const emailInput = document.querySelector(%(email_input_selector)s);
  if (!emailInput) {
    return 'missing-email-input';
  }

  const nextEmail = %(email_value)s;
  if (!nextEmail) {
    return 'empty-email';
  }

  const inputPrototype = window.HTMLInputElement?.prototype;
  const valueSetter = inputPrototype
    ? Object.getOwnPropertyDescriptor(inputPrototype, 'value')?.set
    : null;
  if (valueSetter) {
    valueSetter.call(emailInput, nextEmail);
  } else {
    emailInput.value = nextEmail;
  }
  emailInput.dispatchEvent(new Event('input', { bubbles: true }));

  try {
    const response = await chrome.runtime.sendMessage({
      type: 'SAVE_EMAIL',
      source: 'sidepanel',
      payload: { email: nextEmail },
    });
    if (response?.error) {
      return `save-email-error:${response.error}`;
    }
  } catch (error) {
    return `save-email-runtime-error:${error?.message || String(error)}`;
  }

  return 'saved';
})()
""".strip()

EXTENSION_EMAIL_STATE_SCRIPT_TEMPLATE = """
(async () => {
  const emailInput = document.querySelector(%(email_input_selector)s);

  try {
    const state = await chrome.runtime.sendMessage({
      type: 'GET_STATE',
      source: 'sidepanel',
    });
    return {
      inputEmail: (emailInput?.value || '').trim(),
      hasEmailInput: Boolean(emailInput),
      stateEmail: String(state?.email || '').trim(),
    };
  } catch (error) {
    return {
      error: error?.message || String(error),
      inputEmail: (emailInput?.value || '').trim(),
      hasEmailInput: Boolean(emailInput),
      stateEmail: '',
    };
  }
})()
""".strip()

EXTENSION_STATUS_SNAPSHOT_SCRIPT_TEMPLATE = """
(() => {
  const statusText = document.querySelector(%(status_display_selector)s)?.textContent?.trim() || '';
  const statusBarClass = document.querySelector(%(status_bar_selector)s)?.className || '';
  const autoRunButtonText = document.querySelector(%(auto_run_button_selector)s)?.textContent?.trim() || '';
  const logLines = Array.from(document.querySelectorAll(%(log_line_selector)s))
    .map((element) => (element.textContent || '').trim())
    .filter(Boolean);
  const logCount = logLines.length;
  const recentLogs = logLines.slice(-%(recent_log_limit)s);
  const steps = Array.from(document.querySelectorAll(%(step_status_selector)s)).map((element) => ({
    step: element.getAttribute('data-step') || '',
    text: (element.textContent || '').trim(),
    rowClass: element.closest('.step-row')?.className || '',
  }));
  return {
    statusText,
    statusBarClass,
    autoRunButtonText,
    logCount,
    recentLogs,
    steps,
  };
})()
""".strip()
