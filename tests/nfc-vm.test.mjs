import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import test from 'node:test';

const script = readFileSync(new URL('../scripts/nfc_create_mini_vm.sh', import.meta.url), 'utf8');

test('NFC creator is read-only by default and requires explicit --create', () => {
  assert.match(script, /mode=--check/);
  assert.match(script, /"\$mode" == --create/);
  assert.match(script, /if \[\[ "\$mode" == --check \]\]; then/);
  assert.match(script, /exit 0/);
});
test('NFC creator preserves existing VM identity and volumes', () => {
  assert.match(script, /vm=mini-ai-inference/);
  assert.match(script, /virsh dominfo "\$vm"/);
  assert.match(script, /! -e "\$disk"/);
  assert.match(script, /--name "\$vm"/);
  assert.doesNotMatch(script, /\b(undefine|destroy|virsh shutdown|rm -rf|pool-delete|net-destroy)\b/);
});
test('NFC guest requires key-only SSH, correct cloud init metadata and Canonical checksum', () => {
  assert.match(script, /mini-ai-operator\.pub/);
  assert.match(script, /disable_root: true/);
  assert.match(script, /ssh_pwauth: false/);
  assert.match(script, /sha256sum --check/);
  assert.match(script, /--cloud-init "user-data=\$work\/user-data,meta-data=\$work\/meta-data"/);
});
