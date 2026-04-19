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
PAGE_READY_TIMEOUT_SECONDS = 15.0
BUTTON_CLICK_TIMEOUT_SECONDS = 15.0
RUN_MONITOR_POLL_INTERVAL_SECONDS = 2.0
RUN_MONITOR_STAGNATION_TIMEOUT_SECONDS = 300.0

CLASH_REQUEST_TIMEOUT_SECONDS = 5.0
CLASH_REQUEST_RETRY_ATTEMPTS = 3
CLASH_REQUEST_RETRY_DELAY_SECONDS = 1.0
CLASH_BASE_URL = "http://127.0.0.1:9090"
CLASH_GROUP_NAME = "AI"
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
DEFAULT_PROXY_BLACKLIST_TTL_SECONDS = DEFAULT_LOCAL_BLACKLIST_TTL_SECONDS
PROXY_STATS_FILE_NAME = ".proxy-stats.json"
PROFILE_BLACKLIST_FILE_NAME = ".profile-blacklist.json"
DEFAULT_PROFILE_BLACKLIST_TTL_SECONDS = DEFAULT_LOCAL_BLACKLIST_TTL_SECONDS
PROFILE_BLACKLIST_SIGNAL_TEXTS = ("子账号数量已达上限",)
PROFILE_2925_DOMAIN = "2925.com"
PROFILE_PREFERENCES_RELATIVE_PATH = ("Default", "Preferences")

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

TARGET_EXTENSION_ID = "niignaaoplafnpbcdgcgcajfjddcncgb"
AUTO_RUN_BUTTON_SELECTOR = "#btn-auto-run"
AUTO_RUN_NOW_BUTTON_SELECTOR = "#btn-auto-run-now"
AUTO_START_MODAL_SELECTOR = "#auto-start-modal"
AUTO_START_RESTART_BUTTON_SELECTOR = "#btn-auto-start-restart"
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
