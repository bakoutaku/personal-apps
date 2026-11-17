import { ClaudeIcon, OpenAIIcon } from './BrandIcons';

/** 关于页：数据说明和图标出处。 */
export function AboutPage() {
  return (
    <section className="section about" aria-labelledby="about-h">
      <div className="section-head">
        <div>
          <div className="eyebrow">关于</div>
          <h2 id="about-h">数据与图标</h2>
        </div>
      </div>

      <div className="about-block">
        <h3>Claude 角色素材</h3>
        <p>
          「小克」立绘来自 aklnaaw/dsh-xiaoke-widget，按 CC BY-NC-SA 4.0 分享。
          {' '}<a href={`${import.meta.env.BASE_URL}characters/SOURCE.md`}>素材来源和许可</a>
        </p>
      </div>

      <div className="about-block">
        <h3>供应商图标</h3>
        <p className="about-icons">
          <OpenAIIcon size={20} color="var(--text)" /> <ClaudeIcon size={20} />
        </p>
        <ul className="explain-list">
          <li>
            OpenAI 与 Claude 标识的 SVG 路径取自 simple-icons 15.22.0（CC0 数据），本地打包，不远程加载。商标分别属于 OpenAI 与 Anthropic，使用说明见{' '}
            <a href="https://openai.com/brand/" target="_blank" rel="noreferrer noopener">
              openai.com/brand
            </a>{' '}
            与{' '}
            <a href="https://www.anthropic.com/legal" target="_blank" rel="noreferrer noopener">
              anthropic.com/legal
            </a>
            。
          </li>
          <li>图标只表示数据来源；本应用不是 OpenAI 或 Anthropic 的官方产品，也未获其背书。</li>
        </ul>
      </div>

      <div className="about-block">
        <h3>数据</h3>
        <ul className="explain-list">
          <li>页面只从本机服务读取已导入的记录，不读取日志文件或供应商凭据；令牌和数据不写入浏览器存储或网址。</li>
          <li>token 是记录里的用量，不能换算成订阅额度百分比；缺失的时段不画成 0。</li>
        </ul>
      </div>
    </section>
  );
}
