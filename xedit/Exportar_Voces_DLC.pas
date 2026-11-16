{
  Exportar_Voces_DLC.pas  -  script para FNVEdit (xEdit)

  Como Exportar_Voces.pas, pero para los DLC. Por cada <DLC>_NL.esp cargado crea
    - voces_nl_<DLC>.txt  las respuestas de diálogo (INFO) que son del DLC (no las del juego base),
                          con el mismo formato que voces_nl.txt.
  Y además:
    - voces_tipos.txt     los tipos de voz (VTYP) de FalloutNV.esm Y de los DLC, con su género
                          (sustituye al anterior; incluye también los del juego base).

  El FormID se escribe sin el índice de orden de carga (00xxxxxx), que es como aparece en el
  nombre de los audios dentro del BSA del DLC (p. ej. nvdlc01eli_greeting_00011216_1.ogg).

  Uso: abre FNVEdit marcando los <DLC>_NL.esp (FNVEdit carga solo sus maestros).
       Clic derecho sobre cualquier archivo -> Apply Script -> Exportar_Voces_DLC.
       No modifica nada: al cerrar FNVEdit no hace falta guardar.
  Después: python voces_fnv_vertex.py contar "<Data>\DeadMoney - Main.bsa" "<Edit Scripts>\voces_nl_DeadMoney.txt"
}
unit ExportarVocesDLC;

function Escapar(s: string): string;
begin
  Result := StringReplace(s, #13#10, '{{NL}}', [rfReplaceAll]);
  Result := StringReplace(Result, #10, '{{NL}}', [rfReplaceAll]);
  Result := StringReplace(Result, #13, '{{NL}}', [rfReplaceAll]);
  Result := StringReplace(Result, #9, '{{TAB}}', [rfReplaceAll]);
end;

function Hijo(e: IInterface; texto: string): IInterface;
var
  i: integer;
begin
  Result := nil;
  if not Assigned(e) then Exit;
  for i := 0 to ElementCount(e) - 1 do
    if Pos(LowerCase(texto), LowerCase(Name(ElementByIndex(e, i)))) > 0 then begin
      Result := ElementByIndex(e, i);
      Exit;
    end;
end;

function Valor(e: IInterface): string;
begin
  Result := '';
  if Assigned(e) then Result := GetEditValue(e);
end;

function PrimeraPalabra(s: string): string;
var
  p: integer;
begin
  p := Pos(' ', s);
  if p > 0 then Result := Copy(s, 1, p - 1) else Result := s;
end;

// Exporta las INFO de 'esp' cuyo registro original es de 'nombreEsm'. Devuelve cuántas respuestas.
function ExportarDLC(esp: IInterface; nombreEsm, destino: string): integer;
var
  i, j: integer;
  rec, maestro, resps, respsEn, resp, respEn, trdt: IInterface;
  lista: TStringList;
  formid, numero, emocion, intensidad, mision, notas, nl, en: string;
begin
  Result := 0;
  lista := TStringList.Create;
  for i := 0 to RecordCount(esp) - 1 do begin
    rec := RecordByIndex(esp, i);
    if Signature(rec) <> 'INFO' then Continue;
    maestro := MasterOrSelf(rec);
    if not SameText(GetFileName(GetFile(maestro)), nombreEsm) then Continue;   // solo las del DLC
    resps := ElementByName(rec, 'Responses');
    if not Assigned(resps) then Continue;
    respsEn := ElementByName(maestro, 'Responses');
    formid := IntToHex(GetLoadOrderFormID(rec) and $00FFFFFF, 8);
    mision := PrimeraPalabra(GetElementEditValues(rec, 'QSTI'));
    for j := 0 to ElementCount(resps) - 1 do begin
      resp := ElementByIndex(resps, j);
      trdt := ElementBySignature(resp, 'TRDT');
      numero := Valor(Hijo(trdt, 'Response number'));
      if numero = '' then numero := IntToStr(j + 1);
      emocion := Valor(Hijo(trdt, 'Emotion Type'));
      intensidad := Valor(Hijo(trdt, 'Emotion Value'));
      notas := Valor(ElementBySignature(resp, 'NAM2'));
      nl := Valor(ElementBySignature(resp, 'NAM1'));
      en := '';
      if Assigned(respsEn) and (j < ElementCount(respsEn)) then begin
        respEn := ElementByIndex(respsEn, j);
        en := Valor(ElementBySignature(respEn, 'NAM1'));
      end;
      if nl = '' then Continue;
      lista.Add(formid + #9 + numero + #9 + emocion + #9 + intensidad + #9 + mision + #9
        + Escapar(notas) + #9 + Escapar(nl) + #9 + Escapar(en));
      Result := Result + 1;
    end;
  end;
  lista.SaveToFile(destino);
  lista.Free;
end;

function Initialize: integer;
var
  i, j, n, flags, nDlc: integer;
  f, rec, g: IInterface;
  nombre, dlc: string;
  tipos: TStringList;
begin
  Result := 0;
  nDlc := 0;
  for i := 0 to FileCount - 1 do begin
    f := FileByIndex(i);
    nombre := GetFileName(f);
    if not SameText(Copy(nombre, Length(nombre) - 6, 7), '_NL.esp') then Continue;
    if SameText(nombre, 'FalloutNV_NL.esp') then Continue;
    dlc := Copy(nombre, 1, Length(nombre) - 7);
    AddMessage('Exportando ' + nombre + ' (solo líneas de ' + dlc + '.esm)...');
    n := ExportarDLC(f, dlc + '.esm', ScriptsPath + 'voces_nl_' + dlc + '.txt');
    AddMessage('   ' + IntToStr(n) + ' respuestas -> voces_nl_' + dlc + '.txt');
    nDlc := nDlc + 1;
  end;
  if nDlc = 0 then begin
    AddMessage('ERROR: no hay ningún <DLC>_NL.esp cargado. Marca los .esp de los DLC al abrir FNVEdit.');
    Result := 1;
    Exit;
  end;

  AddMessage('Exportando tipos de voz (juego base y DLC)...');
  tipos := TStringList.Create;
  tipos.Sorted := True;
  tipos.Duplicates := dupIgnore;
  for i := 0 to FileCount - 1 do begin
    f := FileByIndex(i);
    if not SameText(Copy(GetFileName(f), Length(GetFileName(f)) - 3, 4), '.esm') then Continue;
    g := GroupBySignature(f, 'VTYP');
    if not Assigned(g) then Continue;
    for j := 0 to ElementCount(g) - 1 do begin
      rec := ElementByIndex(g, j);
      flags := GetElementNativeValues(rec, 'DNAM');
      if (flags and 2) <> 0 then
        tipos.Add(GetElementEditValues(rec, 'EDID') + #9 + 'F')
      else
        tipos.Add(GetElementEditValues(rec, 'EDID') + #9 + 'M');
    end;
  end;
  tipos.SaveToFile(ScriptsPath + 'voces_tipos.txt');
  AddMessage('   ' + IntToStr(tipos.Count) + ' tipos de voz -> voces_tipos.txt');
  tipos.Free;

  AddMessage('');
  AddMessage('LISTO. Carpeta: ' + ScriptsPath);
  AddMessage('Puedes cerrar FNVEdit sin guardar nada.');
end;

function Process(e: IInterface): integer;
begin
  Result := 0;
end;

end.
