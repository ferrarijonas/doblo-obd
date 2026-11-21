/**
 * Receptor do logger do Doblò: recebe blocos por POST e monta o arquivo da
 * viagem no Drive. Rodar como web app (executar como: eu; acesso: qualquer
 * pessoa com o link).
 *
 * POST .../exec?token=SEGREDO&trip=20261118-210247.csv&off=0&total=312004
 *   corpo = bytes do trecho, texto puro (CSV)
 *
 * Resposta: {"ok":true,"off":<próximo byte>,"recebido":n,"total":n}
 */

const TOKEN = 'TROQUE_ESTE_TOKEN';
const RAIZ = 'doblo';        // pasta no Drive
const VIAGENS = 'viagens';   // subpasta com os arquivos finais

function json(o) {
  return ContentService.createTextOutput(JSON.stringify(o))
    .setMimeType(ContentService.MimeType.JSON);
}

function sub(nome, pai) {
  const it = pai.getFoldersByName(nome);
  return it.hasNext() ? it.next() : pai.createFolder(nome);
}

function raiz() {
  const it = DriveApp.getFoldersByName(RAIZ);
  return it.hasNext() ? it.next() : DriveApp.createFolder(RAIZ);
}

function doGet() {
  return json({ok: true, v: 1});
}

function doPost(e) {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(20000)) return json({ok: false, err: 'ocupado'});

  try {
    const p = e.parameter || {};
    if (p.token !== TOKEN) return json({ok: false, err: 'token'});

    const trip = String(p.trip || '');
    if (!/^[0-9]{8}-[0-9]{6}\.(csv|bin)$/.test(trip)) {
      return json({ok: false, err: 'nome'});
    }

    const off = parseInt(p.off || '0', 10);
    const total = parseInt(p.total || '-1', 10);
    const corpo = (p.data !== undefined)
      ? String(p.data)
      : ((e.postData && e.postData.contents) ? e.postData.contents : '');
    if (off < 0 || !corpo.length) return json({ok: false, err: 'vazio'});

    // um bloco = um arquivo temporário, nomeado pelo offset
    const tmp = sub('_tmp', raiz());
    const pasta = sub(trip, tmp);
    const nome = 'part-' + ('000000000000' + off).slice(-12);
    pasta.createFile(nome, corpo, MimeType.PLAIN_TEXT);

    // soma o que já chegou
    let recebido = 0;
    const arquivos = [];
    const it = pasta.getFiles();
    while (it.hasNext()) {
      const f = it.next();
      recebido += f.getSize();
      arquivos.push(f);
    }

    if (total >= 0 && recebido >= total) {
      arquivos.sort(function (a, b) {
        return a.getName() < b.getName() ? -1 : 1;
      });
      let texto = '';
      for (let i = 0; i < arquivos.length; i++) texto += arquivos[i].getBlob().getDataAsString();
      sub(VIAGENS, raiz()).createFile(trip, texto, MimeType.PLAIN_TEXT);
      pasta.setTrashed(true);
    }

    return json({ok: true, off: off + corpo.length, recebido: recebido, total: total});
  } catch (err) {
    return json({ok: false, err: String(err)});
  } finally {
    lock.releaseLock();
  }
}
