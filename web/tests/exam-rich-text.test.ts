import test from "node:test";
import assert from "node:assert/strict";
import {
  decodeHtmlEntities,
  normalizeExamRichText,
} from "../lib/exam-rich-text";

test("decodeHtmlEntities handles emsp nbsp and amp", () => {
  assert.equal(decodeHtmlEntities("A&emsp;&emsp;B"), "A\u3000\u3000B");
  assert.equal(decodeHtmlEntities("x&nbsp;y"), "x\u00a0y");
  assert.equal(decodeHtmlEntities("&amp;lt;"), "&lt;");
});

test("normalizeExamRichText turns br and entities into readable text", () => {
  const raw =
    "证券服务机构应当勤勉尽责，对所依据的文件资料内容的(&emsp;&emsp;)进行核查和验证。<br /> I.真实性<br /> II.准确性<br /> III.公正性<br /> IV.完整性";
  const out = normalizeExamRichText(raw);
  assert.ok(!out.includes("&emsp;"));
  assert.ok(!out.includes("<br"));
  assert.ok(out.includes("I.真实性"));
  assert.ok(out.includes("II.准确性"));
  assert.match(out, /\n/);
  // emsp becomes ideographic fullwidth spaces for Chinese blanks
  assert.ok(out.includes("(\u3000\u3000)"));
});

test("normalizeExamRichText strips leftover tags safely", () => {
  assert.equal(
    normalizeExamRichText("<b>重点</b>内容&nbsp;OK"),
    "重点内容 OK",
  );
});

test("normalizeExamRichText empty input", () => {
  assert.equal(normalizeExamRichText(""), "");
  assert.equal(normalizeExamRichText(null), "");
  assert.equal(normalizeExamRichText(undefined), "");
});
