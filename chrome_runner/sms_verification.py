"""SMS verification code automation driven by extension logs."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .constants import (
    DEFAULT_SMS_CODE_INPUT_SELECTORS,
    DEFAULT_SMS_CODE_SUBMIT_TEXTS,
    DEVTOOLS_POLL_INTERVAL_SECONDS,
    DEVTOOLS_TARGET_DISCOVERY_TIMEOUT_SECONDS,
    PAGE_READY_TIMEOUT_SECONDS,
    SMS_CODE_SUBMIT_DISCOVERY_TIMEOUT_SECONDS,
    SMS_VERIFICATION_LOG_SIGNAL_TEXTS,
)
from .devtools import (
    DevToolsClient,
    evaluate_javascript,
    wait_for_page_target,
)
from .sms import SmsCodeReceiver

if TYPE_CHECKING:
    from .extension import ExtensionSnapshot


SMS_CODE_FILL_SCRIPT_TEMPLATE = """
(() => {
  const code = %(code)s;
  const explicitSelector = %(input_selector)s;
  const candidateSelectors = %(candidate_selectors)s;
  const uniqueElements = [];
  const seen = new Set();

  const addElement = (element) => {
    if (!element || seen.has(element)) {
      return;
    }
    seen.add(element);
    uniqueElements.push(element);
  };

  const isEditableInput = (element) => (
    (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement)
      && !element.disabled
      && !element.readOnly
  );

  const isVisible = (element) => {
    const style = window.getComputedStyle(element);
    return style.display !== 'none' && style.visibility !== 'hidden';
  };

  const buildInputEvent = (type, value) => {
    if (typeof InputEvent === 'function') {
      return new InputEvent(type, {
        bubbles: true,
        cancelable: type === 'beforeinput',
        data: String(value),
        inputType: 'insertText',
      });
    }
    return new Event(type, {
      bubbles: true,
      cancelable: type === 'beforeinput',
    });
  };

  const getPrototypeValueSetter = (element) => {
    const prototype = element instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
    return Object.getOwnPropertyDescriptor(prototype, 'value')?.set || null;
  };

  const setElementValue = (element, value) => {
    const prototypeValueSetter = getPrototypeValueSetter(element);
    const ownValueSetter = Object.getOwnPropertyDescriptor(element, 'value')?.set || null;

    if (prototypeValueSetter && ownValueSetter && ownValueSetter !== prototypeValueSetter) {
      prototypeValueSetter.call(element, value);
      return;
    }
    if (prototypeValueSetter) {
      prototypeValueSetter.call(element, value);
      return;
    }
    element.value = value;
  };

  const dispatchEvents = (element, value) => {
    element.dispatchEvent(buildInputEvent('beforeinput', value));
    element.dispatchEvent(buildInputEvent('input', value));
    element.dispatchEvent(new Event('change', { bubbles: true }));
    element.blur();
  };

  if (explicitSelector) {
    document.querySelectorAll(explicitSelector).forEach(addElement);
  } else {
    candidateSelectors.forEach((selector) => {
      document.querySelectorAll(selector).forEach(addElement);
    });
  }

  const inputs = uniqueElements.filter(isEditableInput);
  if (!inputs.length) {
    return 'missing-input';
  }

  const visibleInputs = inputs.filter(isVisible);
  const availableInputs = visibleInputs.length ? visibleInputs : inputs;
  const singleCharInputs = availableInputs.filter((element) => Number(element.maxLength || 0) === 1);

  if (singleCharInputs.length >= code.length && code.length > 1) {
    singleCharInputs.slice(0, code.length).forEach((element, index) => {
      const nextValue = code[index] || '';
      element.focus();
      setElementValue(element, nextValue);
      dispatchEvents(element, nextValue);
    });
    return 'filled-split-inputs';
  }

  const target = availableInputs[0];
  target.focus();
  setElementValue(target, code);
  dispatchEvents(target, code);
  return 'filled';
})()
""".strip()

SMS_CODE_SUBMIT_SCRIPT_TEMPLATE = """
(() => {
  const explicitSelector = %(submit_selector)s;
  const submitTexts = %(submit_texts)s.map((item) => String(item).toLowerCase());

  const isVisible = (element) => {
    const style = window.getComputedStyle(element);
    return style.display !== 'none' && style.visibility !== 'hidden';
  };

  const isEnabled = (element) => !element.disabled && element.getAttribute('aria-disabled') !== 'true';

  const normalizeText = (element) => String(
    element.innerText
      || element.textContent
      || element.value
      || element.getAttribute('aria-label')
      || ''
  ).trim().toLowerCase();

  const candidates = [];
  const addElement = (element) => {
    if (!element || !isVisible(element) || !isEnabled(element)) {
      return;
    }
    candidates.push(element);
  };

  if (explicitSelector) {
    document.querySelectorAll(explicitSelector).forEach(addElement);
  } else {
    document
      .querySelectorAll("button, input[type='submit'], input[type='button'], [role='button']")
      .forEach(addElement);
  }

  if (!candidates.length) {
    return 'missing-submit';
  }

  let target = null;
  if (explicitSelector) {
    target = candidates[0];
  } else {
    target = candidates.find((element) => {
      const text = normalizeText(element);
      return submitTexts.some((needle) => text.includes(needle));
    }) || null;
  }

  if (!target) {
    return 'missing-submit';
  }

  target.click();
  return 'clicked-submit';
})()
""".strip()


@dataclass(frozen=True)
class SmsCodeAutomationConfig:
    """Configuration for socket-based SMS verification handling."""

    socket_host: str
    socket_port: int
    code_timeout_seconds: int
    code_regex: str
    input_selector: str = ""
    submit_selector: str = ""


class SmsCodeAutomation:
    """Wait for SMS code request logs, receive a code, and fill the page."""

    def __init__(
        self,
        *,
        devtools_port: int,
        extension_id: str,
        config: SmsCodeAutomationConfig,
    ) -> None:
        self._config = config
        self._devtools_port = devtools_port
        self._excluded_page_prefixes = (
            f"chrome-extension://{extension_id}/",
            "about:blank",
            "devtools://",
        )
        self._receiver = SmsCodeReceiver(
            config.socket_host,
            config.socket_port,
            code_regex=config.code_regex,
        )
        self._handled = False

    def start(self) -> None:
        self._receiver.start()
        print(
            "自动运行前置：短信接收已启动，"
            f"监听 {self._config.socket_host}:{self._receiver.port}。"
        )

    def close(self) -> None:
        self._receiver.close()

    def maybe_handle_snapshot(
        self,
        snapshot: ExtensionSnapshot,
        remaining_attempt_seconds: float | None,
    ) -> None:
        if self._handled or not self._has_sms_trigger(snapshot):
            return

        wait_timeout_seconds = self._resolve_wait_timeout_seconds(
            remaining_attempt_seconds
        )
        print("自动运行前置：检测到验证码等待日志，开始等待短信。")
        received_code = self._receiver.wait_for_code(wait_timeout_seconds)
        print(
            "自动运行前置：已收到短信验证码，"
            f"验证码 {received_code.code}，准备写入页面。"
        )
        submit_clicked = self._fill_code_into_page(
            received_code.code,
            timeout_seconds=wait_timeout_seconds,
        )
        if submit_clicked:
            print("自动运行前置：验证码已写入页面，并已点击提交。")
        else:
            print("自动运行前置：验证码已写入页面，等待页面自行提交。")
        self._handled = True

    def _has_sms_trigger(self, snapshot: ExtensionSnapshot) -> bool:
        return any(
            signal_text in log_line
            for log_line in snapshot.recent_logs
            for signal_text in SMS_VERIFICATION_LOG_SIGNAL_TEXTS
        )

    def _resolve_wait_timeout_seconds(
        self,
        remaining_attempt_seconds: float | None,
    ) -> float:
        timeout_seconds = float(self._config.code_timeout_seconds)
        if remaining_attempt_seconds is None:
            return timeout_seconds
        if remaining_attempt_seconds <= 0:
            raise TimeoutError("当前轮次运行时间已耗尽，无法继续等待短信验证码。")
        return min(timeout_seconds, remaining_attempt_seconds)

    def _fill_code_into_page(
        self,
        code: str,
        *,
        timeout_seconds: float,
    ) -> bool:
        target = wait_for_page_target(
            self._devtools_port,
            excluded_url_prefixes=self._excluded_page_prefixes,
            timeout_seconds=min(timeout_seconds, DEVTOOLS_TARGET_DISCOVERY_TIMEOUT_SECONDS),
        )
        target_url = str(target.get("url", "") or "")
        websocket_url = str(target["webSocketDebuggerUrl"])
        print(f"自动运行前置：当前验证码目标页：{target_url}")
        client = DevToolsClient(
            websocket_url,
            timeout_seconds=max(timeout_seconds, 1.0),
        )
        try:
            client.call("Page.enable")
            client.call("Runtime.enable")
            self._wait_for_code_input_and_fill(
                client,
                code,
                timeout_seconds=min(timeout_seconds, PAGE_READY_TIMEOUT_SECONDS),
            )
            return self._try_click_submit_button(
                client,
                timeout_seconds=min(
                    timeout_seconds,
                    SMS_CODE_SUBMIT_DISCOVERY_TIMEOUT_SECONDS,
                ),
            )
        finally:
            client.close()

    def _wait_for_code_input_and_fill(
        self,
        client: DevToolsClient,
        code: str,
        *,
        timeout_seconds: float,
    ) -> None:
        deadline = time.time() + timeout_seconds
        script = SMS_CODE_FILL_SCRIPT_TEMPLATE % {
            "code": json.dumps(code),
            "input_selector": json.dumps(self._config.input_selector),
            "candidate_selectors": json.dumps(
                DEFAULT_SMS_CODE_INPUT_SELECTORS,
                ensure_ascii=False,
            ),
        }
        while time.time() < deadline:
            result = str(evaluate_javascript(client, script) or "")
            if result in {"filled", "filled-split-inputs"}:
                return
            if result == "missing-input":
                time.sleep(DEVTOOLS_POLL_INTERVAL_SECONDS)
                continue
            raise RuntimeError(f"填写短信验证码失败：{result}")
        raise TimeoutError("页面在预期时间内没有出现可填写验证码的输入框。")

    def _try_click_submit_button(
        self,
        client: DevToolsClient,
        *,
        timeout_seconds: float,
    ) -> bool:
        deadline = time.time() + timeout_seconds
        script = SMS_CODE_SUBMIT_SCRIPT_TEMPLATE % {
            "submit_selector": json.dumps(self._config.submit_selector),
            "submit_texts": json.dumps(
                DEFAULT_SMS_CODE_SUBMIT_TEXTS,
                ensure_ascii=False,
            ),
        }
        while time.time() < deadline:
            result = str(evaluate_javascript(client, script) or "")
            if result == "clicked-submit":
                return True
            if result == "missing-submit":
                time.sleep(DEVTOOLS_POLL_INTERVAL_SECONDS)
                continue
            raise RuntimeError(f"点击验证码提交按钮失败：{result}")
        return False
