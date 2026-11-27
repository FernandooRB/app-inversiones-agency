// Check market source comparison with invented values in a fresh browser context.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

module.exports = async ({browser, out, url, practiceOnly = false}) => {
  const context = await browser.newContext({viewport: {width: 1440, height: 1000}});
  const page = await context.newPage();
  page.setDefaultTimeout(45000);
  const title = 'Cotejar precios, tipos de cambio y tasas';
  const summary = '6 observaciones · 3 comparables · 4 por revisar';
  const panel = page.getByText(title, {exact: true}).locator('xpath=ancestor::details[1]');
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const ready = async () => {
    await page.waitForTimeout(400);
    await page.locator('.stApp[data-test-script-state="notRunning"]').waitFor();
  };
  async function download(label, name) {
    const event = page.waitForEvent('download');
    await panel.getByRole('button', {name: label, exact: true}).click();
    const dest = path.join(out, name);
    await (await event).saveAs(dest);
    return fs.readFileSync(dest);
  }
  try {
    const start = Date.now();
    await page.goto(url);
    await page.getByRole('tab', {name: 'Fuentes y alertas', exact: true}).click();
    await panel.locator('summary').first().focus();
    await panel.locator('summary').first().press('Enter');
    await ready();
    const panelMs = Date.now() - start;
    assert.equal(await panel.getByText(summary, {exact: true}).count(), 0);
    const primary = await download('Descargar CSV principal ficticio', 'mercado_principal_ficticio.csv');
    const reference = await download('Descargar CSV de referencia ficticio', 'mercado_referencia_ficticia.csv');
    const compare = panel.getByRole('button', {name: 'Cotejar observaciones', exact: true});
    const comparisonStart = Date.now();
    await compare.click();
    await panel.getByText(summary, {exact: true}).waitFor();
    const comparisonMs = Date.now() - comparisonStart;
    await panel.getByText('USD/MXN · 2026-01-08 · Fuera del umbral', {exact: true}).waitFor();
    await panel.getByText('Principal − referencia: 0.04 · Diferencia: 20 pb', {exact: true}).waitFor();
    const axes = [];
    for (const width of [1440, 768, 390]) {
      await page.setViewportSize({width, height: 1000});
      await ready();
      await panel.getByText(summary, {exact: true}).scrollIntoViewIfNeeded();
      await page.screenshot({path: path.join(out, `market-review-${width}.png`)});
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2));
      await page.addScriptTag({path: require.resolve('axe-core/axe.min.js')});
      const result = await page.evaluate(async () => {
        const result = await axe.run(document, {runOnly: {type: 'tag', values: ['wcag2a','wcag2aa','wcag21aa']}});
        return {violations: result.violations, incomplete: result.incomplete, passes: result.passes.length};
      });
      axes.push({width, ...result});
      assert.deepEqual(result.violations, []);
    }
    await panel.getByText('Descargar evidencia del cotejo', {exact: true}).click();
    await ready();
    const practice = JSON.parse(await download('Descargar cotejo JSON', 'mercado_cotejo_practica.json'));
    assert.equal(practice.practice, true);
    assert.equal(practice.review_state, 'PENDIENTE_COTEJO_HUMANO');
    assert.deepEqual(practice.counts, {DIFERENCIA:1, NO_COMPARABLE:2, FALTA_REFERENCIA:1, DENTRO:2});
    if (practiceOnly) {
      assert.equal(await panel.getByText('Cargar dos CSV', {exact:true}).count(), 0);
      assert.equal(await panel.getByTestId('stFileUploader').count(), 0);
    } else {
    await panel.getByText('Cargar dos CSV', {exact: true}).click();
    await ready();
    assert.equal(await panel.getByText(summary, {exact: true}).count(), 0);
    assert(await compare.isDisabled());
    for (const [label, name, buffer] of [
      ['Observaciones de la fuente principal', 'mercado_principal_ficticio.csv', primary],
      ['Observaciones de la fuente de referencia', 'mercado_referencia_ficticia.csv', reference],
    ]) {
      await panel.getByTestId('stFileUploader').filter({hasText: label}).locator('input[type=file]')
        .setInputFiles({name, mimeType: 'text/csv', buffer});
      await ready();
    }
    assert(await compare.isDisabled());
    const rights = panel.getByRole('checkbox', {name: 'Confirmo que puedo cotejar ambos archivos y documenté su origen'});
    await rights.focus();
    await rights.press('Space');
    await ready();
    await compare.click();
    await panel.getByText(summary, {exact: true}).waitFor();
    const invalidReference = reference.toString().replace('20,Proveedor', 'NaN,Proveedor');
    assert.notEqual(invalidReference, reference.toString());
    await panel.getByTestId('stFileUploader').filter({hasText: 'Observaciones de la fuente de referencia'})
      .locator('input[type=file]').setInputFiles({name:'invalido_ficticio.csv',mimeType:'text/csv',buffer:Buffer.from(invalidReference)});
    await ready();
    assert(await compare.isDisabled());
    assert.equal(await panel.getByText(summary, {exact: true}).count(), 0);
    await rights.focus();
    await rights.press('Space');
    await ready();
    await compare.click();
    await panel.getByText('Referencia, fila 3: revisa Valor.', {exact: true}).waitFor();
    }
    await panel.getByRole('button', {name: 'Vaciar cotejo', exact: true}).click();
    await ready();
    assert.equal(await panel.getByText(summary, {exact: true}).count(), 0);
    assert.equal(await page.getByTestId('stException').count(), 0);
    assert.equal(errors.length, 0);
    const evidence = {fictional_only:true, pane_ms:panelMs, compare_ms:comparisonMs, axes,
      download_same_counts:true, upload_and_renew_consent:!practiceOnly, invalid_file_rejected:!practiceOnly,
      practice_only:practiceOnly,
      cleared:true, keyboard:true, physical_device:false};
    fs.writeFileSync(path.join(out,'market_review_verification.json'),JSON.stringify(evidence,null,2));
    return evidence;
  } catch (error) {
    await page.screenshot({path:path.join(out,'market-review-failure.png')}).catch(()=>{});
    await page.locator('body').ariaSnapshot().then(body => fs.writeFileSync(path.join(out,'market-review-failure.txt'),body)).catch(()=>{});
    throw error;
  } finally {
    await context.close();
  }
};
