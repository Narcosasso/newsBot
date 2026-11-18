import { Header, Icon } from "../ui";

export function SoonScreen({ title, icon, text }: { title: string; icon: string; text: string }) {
  return (
    <>
      <Header title={title} />
      <div class="empty">
        <Icon name={icon} size={56} />
        <h2>In arrivo</h2>
        <p class="muted">{text}</p>
      </div>
    </>
  );
}
