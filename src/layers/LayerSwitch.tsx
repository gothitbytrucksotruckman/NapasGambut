// Layer switch (PRD 7.2): condition, HH, HV, coherence, radar picture. A radio group, so arrows move between options.
import { LAYERS, type Lang, type LayerId } from '../state/hash';
import { type Key, t } from '../i18n';
import './LayerSwitch.css';

export function LayerSwitch({ layer, lang, onChange }: { layer: LayerId; lang: Lang; onChange: (l: LayerId) => void }) {
  return (
    <fieldset className="layer-switch">
      <legend className="layer-switch__legend">{t(lang, 'layer.label')}</legend>
      <div className="layer-switch__opts">
        {LAYERS.map((l) => (
          <label key={l} className={l === layer ? 'is-on' : undefined}>
            <input type="radio" name="map-layer" value={l} checked={l === layer} onChange={() => onChange(l)} />
            {t(lang, `layer.${l}` as Key)}
          </label>
        ))}
      </div>
    </fieldset>
  );
}
