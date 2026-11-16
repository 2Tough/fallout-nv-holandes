{
  Traduccion_NL.pas  -  script para FNVEdit (xEdit)

  Crea un plugin .esp con los textos de Fallout: New Vegas traducidos al holandés,
  sin modificar FalloutNV.esm.

  Necesita, en la misma carpeta "Edit Scripts" que este archivo:
    - traducciones_nl.txt   (creado con: python traducir_fnv.py exportar-xedit ...)
    - campos_nl.txt         (idem)
    - gmst_nl.txt           (opcional: textos del interfaz, creado con: python traducir_fnv.py gmst ...)

  Uso: en FNVEdit, clic derecho sobre FalloutNV.esm -> Apply Script -> Traduccion_NL.
  Cuando pida el nombre del nuevo archivo, escribe: FalloutNV_NL

  Versión 2:
  - Busca el texto también dentro de subelementos (p. ej. el texto de las notas, NOTE TNAM,
    que FNVEdit guarda dentro de otro elemento y antes no se encontraba).
  - Compara sin tener en cuenta espacios ni saltos de línea sobrantes en los extremos.
  - Añade los Game Settings (menús, botones, mensajes del interfaz) desde gmst_nl.txt.
}
unit TraduccionNL;

var
  claves, valores, campos, tipos, gmstClaves, gmstValores: TStringList;
  plugin: IInterface;
  nRegistros, nTextos, nGmst: integer;

// Clave de búsqueda: debe coincidir con clave_xedit() de traducir_fnv.py
function Clave(s: string): string;
begin
  Result := StringReplace(s, #13, ' ', [rfReplaceAll]);
  Result := StringReplace(Result, #10, ' ', [rfReplaceAll]);
  Result := StringReplace(Result, #9, ' ', [rfReplaceAll]);
  while Pos('  ', Result) > 0 do
    Result := StringReplace(Result, '  ', ' ', [rfReplaceAll]);
  Result := Trim(Result);
end;

function EsEspacio(c: string): boolean;
begin
  Result := (c = ' ') or (c = #9) or (c = #10) or (c = #13);
end;

function Desescapar(s, salto: string): string;
begin
  Result := StringReplace(s, '{{NL}}', salto, [rfReplaceAll]);
  Result := StringReplace(Result, '{{TAB}}', #9, [rfReplaceAll]);
end;

// Posición de la traducción en "valores", o -1 si este elemento no tiene texto traducido.
// sigCampo es la firma del subregistro (FULL, DESC, TNAM...) aunque el texto esté más adentro.
function Buscar(sigRec, sigCampo: string; e: IInterface): integer;
var
  s: string;
  i: integer;
begin
  Result := -1;
  if campos.IndexOf(sigRec + ':' + sigCampo) < 0 then Exit;
  s := Clave(GetEditValue(e));
  if s = '' then Exit;
  i := claves.IndexOf(s);
  if i >= 0 then
    Result := Integer(claves.Objects[i]);
end;

function TieneTexto(sigRec, sigPadre: string; e: IInterface): boolean;
var
  i: integer;
  sigCampo: string;
begin
  Result := False;
  sigCampo := Signature(e);
  if sigCampo = '' then sigCampo := sigPadre;
  if Buscar(sigRec, sigCampo, e) >= 0 then begin
    Result := True;
    Exit;
  end;
  for i := 0 to ElementCount(e) - 1 do
    if TieneTexto(sigRec, sigCampo, ElementByIndex(e, i)) then begin
      Result := True;
      Exit;
    end;
end;

function Aplicar(sigRec, sigPadre: string; e: IInterface): integer;
var
  i, k, n: integer;
  original, nuevo, salto, inicio, fin, sigCampo: string;
begin
  Result := 0;
  sigCampo := Signature(e);
  if sigCampo = '' then sigCampo := sigPadre;
  k := Buscar(sigRec, sigCampo, e);
  if k >= 0 then begin
    original := GetEditValue(e);
    if Pos(#13#10, original) > 0 then
      salto := #13#10
    else
      salto := #10;
    // conservar los espacios y saltos de línea de los extremos del original
    inicio := '';
    n := 1;
    while (n <= Length(original)) and EsEspacio(Copy(original, n, 1)) do begin
      inicio := inicio + Copy(original, n, 1);
      n := n + 1;
    end;
    fin := '';
    n := Length(original);
    while (n > Length(inicio)) and EsEspacio(Copy(original, n, 1)) do begin
      fin := Copy(original, n, 1) + fin;
      n := n - 1;
    end;
    nuevo := inicio + Desescapar(valores[k], salto) + fin;
    SetEditValue(e, nuevo);
    Result := 1;
    Exit;
  end;
  for i := 0 to ElementCount(e) - 1 do
    Result := Result + Aplicar(sigRec, sigCampo, ElementByIndex(e, i));
end;

function CargarPares(ruta: string; cl, va: TStringList): integer;
var
  i, p: integer;
  lineas: TStringList;
  linea: string;
begin
  Result := 0;
  if not FileExists(ruta) then Exit;
  lineas := TStringList.Create;
  lineas.LoadFromFile(ruta);
  for i := 0 to lineas.Count - 1 do begin
    linea := lineas[i];
    p := Pos(#9, linea);
    if p > 1 then begin
      va.Add(Copy(linea, p + 1, Length(linea)));
      cl.AddObject(Copy(linea, 1, p - 1), TObject(va.Count - 1));
    end;
  end;
  lineas.Free;
  Result := cl.Count;
end;

procedure AplicarGMST(f: IInterface);
var
  i, k: integer;
  g, rec, ov, e: IInterface;
  nuevo: string;
begin
  if gmstClaves.Count = 0 then Exit;
  AddMessage('Añadiendo los textos del interfaz (Game Settings)...');
  g := GroupBySignature(f, 'GMST');
  for i := 0 to ElementCount(g) - 1 do begin
    rec := ElementByIndex(g, i);
    k := gmstClaves.IndexOf(GetElementEditValues(rec, 'EDID'));
    if k >= 0 then begin
      ov := wbCopyElementToFile(rec, plugin, False, True);
      if Assigned(ov) then begin
        e := ElementBySignature(ov, 'DATA');
        if Assigned(e) then begin
          nuevo := Desescapar(gmstValores[Integer(gmstClaves.Objects[k])], #13#10);
          if (GetEditValue(e) = '') and (ElementCount(e) > 0) then
            e := ElementByIndex(e, 0);
          SetEditValue(e, nuevo);
          nGmst := nGmst + 1;
        end;
      end;
    end;
  end;
end;

function Initialize: integer;
var
  i: integer;
  lineas: TStringList;
  linea, sigRec: string;
  f, rec, ov: IInterface;
begin
  Result := 0;
  nRegistros := 0;
  nTextos := 0;
  nGmst := 0;

  claves := TStringList.Create;
  claves.CaseSensitive := True;
  claves.Sorted := True;
  claves.Duplicates := dupIgnore;
  valores := TStringList.Create;
  gmstClaves := TStringList.Create;
  gmstClaves.CaseSensitive := False;
  gmstClaves.Sorted := True;
  gmstClaves.Duplicates := dupIgnore;
  gmstValores := TStringList.Create;
  campos := TStringList.Create;
  campos.Sorted := True;
  campos.Duplicates := dupIgnore;
  tipos := TStringList.Create;
  tipos.Sorted := True;
  tipos.Duplicates := dupIgnore;

  if not FileExists(ScriptsPath + 'traducciones_nl.txt') then begin
    AddMessage('ERROR: no encuentro traducciones_nl.txt en ' + ScriptsPath);
    Result := 1;
    Exit;
  end;
  if not FileExists(ScriptsPath + 'campos_nl.txt') then begin
    AddMessage('ERROR: no encuentro campos_nl.txt en ' + ScriptsPath);
    Result := 1;
    Exit;
  end;

  AddMessage('Leyendo traducciones...');
  CargarPares(ScriptsPath + 'traducciones_nl.txt', claves, valores);
  CargarPares(ScriptsPath + 'gmst_nl.txt', gmstClaves, gmstValores);
  lineas := TStringList.Create;
  lineas.LoadFromFile(ScriptsPath + 'campos_nl.txt');
  for i := 0 to lineas.Count - 1 do begin
    linea := Trim(lineas[i]);
    if Length(linea) = 9 then begin
      campos.Add(linea);
      tipos.Add(Copy(linea, 1, 4));
    end;
  end;
  lineas.Free;
  AddMessage(IntToStr(claves.Count) + ' traducciones, ' + IntToStr(campos.Count) + ' tipos de campo y '
    + IntToStr(gmstClaves.Count) + ' textos del interfaz cargados.');
  if gmstClaves.Count = 0 then
    AddMessage('(No hay gmst_nl.txt: los menús y botones quedarán en inglés.)');

  f := nil;
  for i := 0 to FileCount - 1 do
    if SameText(GetFileName(FileByIndex(i)), 'FalloutNV.esm') then
      f := FileByIndex(i);
  if not Assigned(f) then begin
    AddMessage('ERROR: FalloutNV.esm no está cargado en FNVEdit.');
    Result := 1;
    Exit;
  end;

  AddMessage('Escribe el nombre del nuevo plugin: FalloutNV_NL');
  plugin := AddNewFile;
  if not Assigned(plugin) then begin
    AddMessage('Cancelado: no se creó el plugin.');
    Result := 1;
    Exit;
  end;
  AddMasterIfMissing(plugin, 'FalloutNV.esm');

  AddMessage('Creando el plugin. Puede tardar bastante; no cierres FNVEdit...');
  for i := 0 to RecordCount(f) - 1 do begin
    rec := RecordByIndex(f, i);
    sigRec := Signature(rec);
    if (sigRec <> 'GMST') and (tipos.IndexOf(sigRec) >= 0) then
      if TieneTexto(sigRec, '', rec) then begin
        ov := wbCopyElementToFile(rec, plugin, False, True);
        if Assigned(ov) then begin
          nTextos := nTextos + Aplicar(sigRec, '', ov);
          nRegistros := nRegistros + 1;
        end;
      end;
    if (i mod 50000) = 0 then
      AddMessage('  ' + IntToStr(i) + ' de ' + IntToStr(RecordCount(f)) + ' registros revisados...');
  end;
  AplicarGMST(f);
end;

function Process(e: IInterface): integer;
begin
  Result := 0;
end;

function Finalize: integer;
begin
  Result := 0;
  AddMessage('');
  AddMessage('LISTO: ' + IntToStr(nTextos) + ' textos traducidos en ' + IntToStr(nRegistros) + ' registros.');
  AddMessage('Textos del interfaz (Game Settings): ' + IntToStr(nGmst));
  AddMessage('Cierra FNVEdit y, cuando pregunte, guarda FalloutNV_NL.esp (dejalo marcado y pulsa OK).');
  claves.Free;
  valores.Free;
  gmstClaves.Free;
  gmstValores.Free;
  campos.Free;
  tipos.Free;
end;

end.
